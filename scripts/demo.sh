#!/usr/bin/env bash
# VAULT end-to-end demo: upload -> node failure -> auto-repair -> corruption
# -> verify -> partition -> reconnect -> rebalance. Requires the server running.
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8000}"
PY="${PY:-python3}"
command -v curl >/dev/null 2>&1 || { echo "curl is required"; exit 1; }

say() { printf "\n\033[1;36m== %s ==\033[0m\n" "$1"; }

jsonget() { "$PY" -c "import json,sys;d=json.load(sys.stdin);print($1)"; }

say "System health"
curl -sf "$BASE/api/health" | jsonget "d"

say "Upload object (RF=3)"
OID=$(curl -sf -X POST -F "file=@backend/requirements.txt" \
  "$BASE/api/files/upload?replication_factor=3" | jsonget "d['object_id']")
echo "object_id=$OID"

say "Replica placement"
curl -sf "$BASE/api/files/$OID/replicas" | jsonget "[(r['node_id'], r['status']) for r in d['replicas']]"

say "PHASE 4: Simulate node2 failure"
curl -sf -X POST "$BASE/api/nodes/node2/fail" | jsonget "d['message']"
sleep 7   # allow the repair worker to drain the queue

say "Object state after automatic repair"
curl -sf "$BASE/api/files/$OID" | jsonget "(d['status'], [(r['node_id'], r['status']) for r in d['replicas']])"

say "Repair jobs"
curl -sf "$BASE/api/repairs?limit=5" | jsonget "[(j['status'], j['reason'], j['failed_node_id']) for j in d]"

say "PHASE 7: Corrupt the node3 replica"
curl -sf -X POST "$BASE/api/files/$OID/corrupt?node_id=node3" | jsonget "(d['replica_id'], 'detected=', d['detected'])"

say "Repair queue after corruption detection"
curl -sf "$BASE/api/repairs?limit=5" | jsonget "[(j['status'], j['failed_node_id'], j['reason']) for j in d]"
sleep 7

say "Object state after corruption repair"
curl -sf "$BASE/api/files/$OID" | jsonget "(d['status'], [(r['node_id'], r['status']) for r in d['replicas']])"

say "PHASE 9: Partition node4, then download (must still succeed)"
curl -sf -X POST "$BASE/api/nodes/node4/partition" | jsonget "d['message']"
curl -sf "$BASE/api/files/$OID/download" -o /tmp/vault_dl.bin -w "download http=%{http_code} size=%{size_download}\n"

say "PHASE 10: Reconnect node4"
curl -sf -X POST "$BASE/api/nodes/node4/reconnect" | jsonget "d['message']"

say "PHASE 11: Trigger rebalance (moves only if threshold exceeded)"
curl -sf -X POST "$BASE/api/rebalance" | jsonget "(d['planned'], d['completed'], d['failed'])"

say "Final integrity verification"
curl -sf -X POST "$BASE/api/files/$OID/verify" | jsonget "(d['integrity'], d['verified'], '/', d['replicas_checked'])"

say "System stats"
curl -sf "$BASE/api/system/stats" | jsonget "{k: d[k] for k in ('status','nodes_online','total_objects','active_repair_jobs','logical_storage','physical_storage')}"

say "DEMO COMPLETE"

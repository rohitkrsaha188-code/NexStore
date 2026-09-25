# NexStore

**Fault-tolerant distributed object storage — store, replicate, verify, repair, and rebalance across simulated independent storage nodes.**

NexStore demonstrates the complete lifecycle of a distributed storage platform:
replicated uploads with least-utilized placement, automatic repair after node
failure or silent corruption, SHA-256 integrity verification, network
partition handling with reconciliation, background rebalancing, recovery
metrics, and a professional live dashboard that reflects real backend state.

---

## Features

- **Replicated object storage** — configurable RF (1–5), never co-locating replicas of one object
- **Automatic repair** — node failures and corruption self-heal in the background, verified by checksum
- **Integrity verification** — SHA-256 on upload, on download, and on periodic cluster scans
- **Failure simulation** — crash, restore, partition, reconnect, corrupt — all through real backend endpoints
- **Network partition handling** — metadata retained, stale replicas reconciled on reconnect
- **Rebalancing** — verified moves from over- to under-utilized nodes (verify-before-delete)
- **Concurrency safety** — serialized atomic metadata writes, optimistic versioning, duplicate-repair protection
- **Observability** — activity feed, repair metrics, average recovery time, storage overhead (logical vs physical)
- **Professional dashboard** — topology view, node cards, object explorer, repair center, integrity center, live simulator

## Architecture

```
Frontend (vanilla JS)  →  REST API (FastAPI)  →  Services
    →  Distributed storage logic (placement · replication · repair · integrity · rebalancing)
    →  Metadata (SQLite)  +  Storage nodes (storage_nodes/nodeX/data/)
```

The frontend only speaks HTTP to `/api/*` — it never touches node files.
Details: [docs/architecture.md](docs/architecture.md) ·
[docs/system-design.md](docs/system-design.md)

## Project structure

```
NexStore/
├── frontend/            index.html + css/ (5 files) + js/ (14 modules)
├── backend/
│   ├── main.py          app assembly, workers, error handlers, static hosting
│   ├── api/             9 routers (files, nodes, repairs, integrity, …)
│   ├── services/        upload · download · delete · object queries
│   ├── storage/         object_store · node_manager · placement · metrics
│   ├── replication/     replica_manager · consistency · placement_policy
│   ├── integrity/       checksum · verifier · corruption
│   ├── health/          health_checker · failure_detector · heartbeat
│   ├── repair/          repair_queue · repair_manager · repair_worker
│   ├── rebalancing/     rebalancer · migration
│   ├── concurrency/     locks · versioning · request_manager
│   ├── metadata/        metadata_manager · metadata_consistency
│   └── workers/         health · repair · integrity · rebalance loops
├── storage_nodes/       node1..node5/data/  (physical object storage)
├── data/                vault.db (metadata), logs/
├── tests/               13 test files, 71 tests
├── docs/                architecture · system-design · api · replication ·
│                        failure-handling · recovery
├── scripts/demo.sh      end-to-end demo (12 phases)
├── run.py               single-command launcher
└── .env.example         configuration template
```

## Requirements

- Python **3.11+**
- pip
- No Docker/Kubernetes/Redis needed — everything runs locally

## Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt
cp .env.example .env             # optional; defaults are sensible
```

## Running backend & frontend

NexStore is a **single-process app**: the FastAPI backend serves both the REST
API **and** the frontend dashboard (vanilla JS under `frontend/`, mounted at
`/static`). One command runs everything — there is no separate frontend
build step, dev server, or npm install.

### 1. Backend (API + dashboard server)

```bash
# activate the venv created during installation
source .venv/bin/activate          # Windows: .venv\Scripts\activate

python run.py
# equivalent: uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Expected console output:

```
Starting NexStore on http://127.0.0.1:8000
INFO | vault.db            | Database initialized at .../data/vault.db
INFO | vault.node_manager | Initialized 5 storage nodes
INFO | vault.health_worker | Health worker started (interval=5s)
INFO | vault.repair_worker | Repair worker started (interval=5s)
INFO | vault.integrity_worker | Integrity worker started (interval=30s)
INFO | vault.rebalance_worker | Rebalance worker started (interval=30s)
```

First startup automatically: creates the database and tables, registers 5
nodes ONLINE, creates node directories, and starts the four background
workers (health · repair · integrity · rebalance).

### 2. Frontend (dashboard UI)

Nothing to run — the backend serves it. After starting the backend, open:

| URL | What it is |
|---|---|
| **http://127.0.0.1:8000** | the live dashboard (topology, node cards, object explorer, repair/integrity centers, failure simulator) |
| http://127.0.0.1:8000/docs | interactive OpenAPI docs for every endpoint |

The frontend talks to the API with relative `/api/*` calls, so it must be
opened through the backend URL above (opening `frontend/index.html` directly
from disk will not work). Frontend development workflow: edit files under
`frontend/` and refresh the browser — no rebuild.

Different port or host: set `PORT` / `HOST` in `.env` (copy
`.env.example`), then open the new URL.

### 3. Verify it is running

```bash
curl http://127.0.0.1:8000/api/health
```

Sample output:

```json
{
  "status": "healthy",
  "nodes": 5,
  "healthy_nodes": 5,
  "failed_nodes": 0
}
```

`GET /api/nodes` returns the fleet (`node1`–`node5`, all `ONLINE`), and
`GET /api/system/stats` returns cluster-wide numbers (capacity used/available,
logical vs physical storage, replication overhead, object/replica counts,
repair metrics).

### 4. Watch failure → auto-repair end-to-end

With the server running:

```bash
# upload an object with RF=3 (lands on node1, node2, node3)
curl -F "file=@demo.jpg" -F "replication_factor=3" \
     http://127.0.0.1:8000/api/files/upload

# fail node2 — its objects go DEGRADED, repairs queue automatically
curl -X POST http://127.0.0.1:8000/api/nodes/node2/fail

# within seconds the repair worker restores RF=3 on node4:
#   INFO | vault.replica_manager | Replica ... on node4 verified and committed
#   INFO | vault.repair_queue    | Repair ... -> COMPLETED

# restore node2 (it rejoins empty; reconciliation brings it up to date)
curl -X POST http://127.0.0.1:8000/api/nodes/node2/restore
```

Or click the same actions in the dashboard's **Failure Simulator**, and watch
`GET /api/repairs/metrics` (`{"total": 3, "completed": 3, "avg_recovery_ms": 2}`)
plus the Activity feed update live.

## Running tests

```bash
pytest -q                        # 71 tests
pytest tests/test_repair.py -v   # one area
```

Tests run against an isolated temp database/storage per test — they never
touch your dev data.

## Demo workflow

Terminal demo (server must be running):

```bash
bash scripts/demo.sh
```

This walks the full scenario: upload RF=3 → fail node2 → watch automatic
repair (node2 → node4) → corrupt node3's replica → CHECKSUM MISMATCH → repair
→ partition node4 while downloads continue → reconnect → rebalance → final
integrity VERIFIED.

### UI demo (recommended for presentations)

1. **Dashboard** — 5 nodes ONLINE, system HEALTHY
2. **Objects → Upload** — drag a file, RF=3; watch Uploading → Hashing →
   Replicating → Verifying → stored on node1/node2/node3
3. Dashboard → **Failure Simulator** → *Simulate Node Failure* (node2)
   - node2 turns red, object becomes DEGRADED, a repair job appears
   - within seconds: replica restored on node4, object HEALTHY again
4. *Corrupt Replica* — CHECKSUM MISMATCH is detected, repair runs, VERIFIED
5. *Simulate Partition* (node4) — downloads still succeed from other replicas
6. *Reconnect* — node4 reconciles
7. Explore **Repairs** (durations + average recovery time), **Integrity**
   (expected vs actual SHA-256), **Replication** (per-object replica tree),
   **Rebalancing**, **Activity** (live event feed)

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `REPLICATION_FACTOR` | 3 | default RF for uploads |
| `HEALTH_CHECK_INTERVAL` | 5 s | heartbeat refresh cadence (timeout = 3×) |
| `REPAIR_INTERVAL` | 5 s | repair worker poll |
| `INTEGRITY_CHECK_INTERVAL` | 30 s | background SHA-256 scan |
| `REBALANCE_THRESHOLD` | 80 % | node utilization that triggers rebalancing |
| `MAX_STORAGE_PER_NODE` | 10 GiB | per-node capacity |
| `MAX_UPLOAD_SIZE` | 512 MiB | single upload limit |
| `NODE_COUNT` | 5 | simulated fleet size |

All except `NODE_COUNT` can also be changed live in Settings.

## Failure simulation cheat sheet

| UI button | Backend call |
|---|---|
| Simulate Node Failure | `POST /api/nodes/{id}/fail` |
| Restore Node | `POST /api/nodes/{id}/restore` |
| Simulate Partition | `POST /api/nodes/{id}/partition` |
| Reconnect Node | `POST /api/nodes/{id}/reconnect` |
| Corrupt Replica | `POST /api/files/{id}/corrupt` |
| Integrity Scan | `POST /api/integrity/scan` |
| Trigger Rebalance | `POST /api/rebalance` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Backend unreachable` in the UI | server not running — `python run.py` |
| Port 8000 busy | set `PORT=8001` in `.env` |
| Upload rejected `insufficient_healthy_nodes` | restore failed nodes or lower RF |
| Rebalance does nothing | by design — nodes are below the threshold; use `GET /api/rebalance/plan` to preview |
| Strange state after heavy simulation | Settings → save (workers re-read config); or restart — recovery sweeps fix metadata drift |
| Tests fail with DB locked | stop the dev server; tests use their own DB but share the log file |
| Reset everything | stop server, delete `data/vault.db*` and `storage_nodes/*/data/*` |

## Security notes

Filenames are sanitized (path traversal impossible), object IDs are
validated, upload size is enforced, errors never leak stack traces, and
`.env` is git-ignored. Auth is intentionally omitted for the prototype; the
API layer is the single place to add it.

## Documentation

- [docs/architecture.md](docs/architecture.md) — components, data flows, state machines
- [docs/system-design.md](docs/system-design.md) — simulated independence, schema, strategies
- [docs/api.md](docs/api.md) — every endpoint with request/response examples
- [docs/replication.md](docs/replication.md) — placement, consistency, versioning
- [docs/failure-handling.md](docs/failure-handling.md) — failure · partition · corruption workflows
- [docs/recovery.md](docs/recovery.md) — repair pipeline, metrics, rebalancing

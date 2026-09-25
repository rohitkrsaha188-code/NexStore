# VAULT — API Documentation

Base URL: `http://127.0.0.1:8000` (interactive docs at `/docs`)

Errors use a structured JSON envelope — raw stack traces are never exposed:

```json
{ "error": "object_not_found", "message": "Unknown object: obj_x", "detail": {} }
```

| Status | Meaning |
|---|---|
| 404 | object / node / replica not found |
| 409 | version conflict, insufficient healthy nodes, object unavailable, storage full |
| 413 | payload too large |
| 422 | validation error (bad filename, bad settings) |
| 500 | internal error (details logged server-side) |

---

## System

### `GET /api/health`
```json
{ "status": "healthy", "nodes": 5, "healthy_nodes": 5, "failed_nodes": 0 }
```

### `GET /api/system/stats`
Aggregated cluster state:
```json
{
  "status": "DEGRADED",
  "total_capacity": 53687091200,
  "used_capacity": 498,
  "available_capacity": 53687090702,
  "logical_storage": 166,
  "physical_storage": 498,
  "replication_overhead": 332,
  "replication_factor": 3,
  "total_objects": 1,
  "total_replicas": 3,
  "nodes_total": 5, "nodes_online": 4, "nodes_failed": 1, "nodes_partitioned": 0,
  "active_repair_jobs": 1, "completed_repairs": 2, "failed_repairs": 0,
  "avg_repair_ms": 6,
  "corrupted_replicas": 0,
  "system_health": "DEGRADED",
  "per_node": [ { "node_id": "node1", "utilization": 0.0, "...": "..." } ]
}
```

### `GET /api/system/settings` · `PUT /api/system/settings`
```json
// PUT body (any subset)
{ "replication_factor": 3, "health_check_interval": 5, "repair_interval": 5,
  "integrity_check_interval": 30, "rebalance_threshold": 80,
  "max_storage_per_node": 10737418240 }
```
Invalid values → `422` (e.g. `replication_factor` must be 1–5).

### `GET /api/system/events?limit=50`
Severity-tagged system journal.

---

## Nodes

| Endpoint | Effect |
|---|---|
| `GET /api/nodes` | list all nodes with utilization |
| `GET /api/nodes/{node_id}` | one node |
| `GET /api/nodes/{node_id}/replicas` | replicas stored on the node |
| `POST /api/nodes/{node_id}/fail` | simulate crash → replicas UNAVAILABLE, repairs scheduled |
| `POST /api/nodes/{node_id}/restore` | return to ONLINE; stale replicas queued for reconciliation |
| `POST /api/nodes/{node_id}/partition` | PARTITIONED — metadata retained, temporarily unreachable |
| `POST /api/nodes/{node_id}/reconnect` | reconnect + reconcile |

```json
// POST /api/nodes/node2/fail →
{ "node_id": "node2", "status": "FAILED", "network_status": "DISCONNECTED",
  "message": "Node node2 failed; degraded objects scheduled for repair" }
```

---

## Files / objects

### `GET /api/files`
```json
[ { "object_id": "obj_…", "filename": "photo.jpg", "size": 2497311,
    "checksum": "81b2…", "version": 1, "replication_factor": 3,
    "status": "HEALTHY", "replica_count": 3, "healthy_replicas": 3,
    "required_replicas": 3, "missing_replicas": 0, "updated_at": "…" } ]
```

### `POST /api/files/upload`
`multipart/form-data`: `file` (required), query `replication_factor` (1–5, optional).
```json
// 200
{ "object_id": "obj_…", "filename": "requirements.txt", "size": 166,
  "checksum": "81b2…", "version": 1, "replication_factor": 3, "status": "HEALTHY",
  "replicas": [ { "replica_id": "rep_…_node1", "node_id": "node1", "status": "HEALTHY", "…": "…" } ],
  "placement": { "nodes": ["node1","node2","node3"], "strategy": "least-utilized-greedy" } }
// 409 insufficient_healthy_nodes — not enough ONLINE nodes for the requested RF
// 413 payload_too_large · 422 invalid_filename
```

### `GET /api/files/{object_id}/download`
Streams the bytes after SHA-256 verification, choosing a healthy replica
(round-robin start). Response headers include `X-Served-From-Node` and
`X-Integrity: VERIFIED`. Corrupted replicas are skipped, marked, and repaired.
`409 object_unavailable` if no replica verifies.

### `DELETE /api/files/{object_id}`
```json
{ "object_id": "obj_…", "filename": "requirements.txt",
  "deleted_replicas": 3, "warnings": [] }
```

### `GET /api/files/{object_id}/replicas`
```json
{ "object_id": "obj_…", "required": 3,
  "replicas": [ { "node_id": "node1", "status": "HEALTHY", "version": 1, "…": "…" } ] }
```

### `POST /api/files/{object_id}/verify`
```json
{ "object_id": "obj_…", "replicas_checked": 3, "verified": 3, "corrupted": 0,
  "repaired_scheduled": 0, "integrity": "VERIFIED",
  "results": [ { "replica_id": "…", "node_id": "node1", "verified": true,
                 "expected_checksum": "81b2…", "actual_checksum": "81b2…" } ] }
```

### `POST /api/files/{object_id}/corrupt?node_id=node3`
Simulates silent corruption of one healthy replica; immediately verifies and
schedules repair. Returns `{ "replica_id": "…", "node_id": "node3",
"object_id": "…", "detected": true }`.

---

## Replicas · consistency

| Endpoint | Purpose |
|---|---|
| `GET /api/replicas?object_id=…` | all/one object's replicas |
| `GET /api/replicas/{replica_id}` | one replica |
| `GET /api/replicas/consistency/{object_id}` | stale/divergent detection vs authoritative version+checksum |

```json
// consistency →
{ "object_id": "obj_…", "authoritative_version": 1,
  "authoritative_checksum": "81b2…", "consistent": true,
  "stale_replicas": [], "divergent_replicas": [] }
```

---

## Repairs

| Endpoint | Purpose |
|---|---|
| `GET /api/repairs?status=…&limit=…` | job history |
| `POST /api/repairs/{repair_id}/retry` | re-queue a failed job |
| `GET /api/repairs/metrics` | totals + average recovery time |

```json
// metrics →
{ "total": 5, "queued": 0, "running": 0, "completed": 5, "failed": 0,
  "avg_recovery_ms": 6 }
```

---

## Integrity

| Endpoint | Purpose |
|---|---|
| `POST /api/integrity/scan` | full-cluster SHA-256 verification; schedules repairs |
| `GET /api/integrity/report` | expected vs actual checksum per replica |
| `POST /api/integrity/replica/{replica_id}/verify` | verify a single replica |

---

## Rebalancing

| Endpoint | Purpose |
|---|---|
| `POST /api/rebalance?max_moves=5` | execute moves now |
| `GET /api/rebalance/plan` | preview planned moves |
| `GET /api/rebalance/status` | aggregate status |
| `GET /api/rebalance/jobs` | movement history |

```json
// POST /api/rebalance →
{ "planned": 2, "completed": 2, "failed": 0,
  "moves": [ { "replica_id": "…", "source_node_id": "node1",
               "dest_node_id": "node4", "size": 12345, "status": "COMPLETED" } ] }
```

---

## Activity

### `GET /api/activity?limit=100`
```json
[ { "id": 42, "event_type": "REPAIR_COMPLETED",
    "message": "Repair repjob_… -> COMPLETED",
    "object_id": "obj_…", "node_id": null, "created_at": "2026-…" } ]
```

Event types: `OBJECT_UPLOADED · OBJECT_DOWNLOADED · OBJECT_DELETED ·
REPLICA_CREATED · REPLICA_DELETED · REPLICA_REPAIRED · REPLICA_MIGRATED ·
REPLICA_RECONCILED · NODE_FAILED · NODE_RECOVERED · REPAIR_STARTED ·
REPAIR_COMPLETED · REPAIR_FAILED · CHECKSUM_VERIFIED · CORRUPTION_DETECTED ·
CORRUPTION_SIMULATED · REBALANCE_STARTED · REBALANCE_COMPLETED ·
NETWORK_PARTITION · OBJECT_STATUS_CHANGED · NODE_REGISTERED · SYSTEM_START`

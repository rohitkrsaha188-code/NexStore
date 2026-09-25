# VAULT — Architecture

## System overview

VAULT is a layered distributed object storage simulator. Five logically
independent storage nodes run as directories on one machine, coordinated by a
FastAPI application that owns all metadata in SQLite.

```
┌────────────────────────────────────────────────────┐
│  Frontend (vanilla JS dashboard)                   │
│  fetch() → /api/* only; never touches node files   │
└───────────────────────┬────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────┐
│  REST API (FastAPI routers)                        │
│  files · nodes · replicas · repairs · integrity    │
│  rebalance · activity · health · system            │
└───────────────────────┬────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────┐
│  Application services                              │
│  UploadService · DownloadService · DeleteService   │
│  object_service (queries)                          │
└───────────────────────┬────────────────────────────┘
                        ▼
┌────────────────────────────────────────────────────┐
│  Distributed storage logic                         │
│  placement policy · replica manager · repair       │
│  manager/queue · rebalancer · integrity verifier   │
│  health checker · failure detector · consistency   │
└──────────────┬───────────────────┬─────────────────┘
               ▼                   ▼
┌──────────────────────┐  ┌──────────────────────────┐
│ Metadata (SQLite)    │  │ Storage nodes (filesystem)│
│ nodes · objects      │  │ storage_nodes/node1/data  │
│ replicas · repairs   │  │ storage_nodes/node2/data  │
│ rebalance · activity │  │ … node5/data              │
└──────────────────────┘  └──────────────────────────┘
```

### Layering rules

1. **The frontend never touches storage-node files.** Every byte and every
   state change flows through the REST API.
2. **Metadata lives only in SQLite.** Object bytes live only under
   `storage_nodes/nodeX/data/`. Neither duplicates the other.
3. **All metadata mutations are serialized.** `Database.write()` holds a
   process-wide lock and a transaction — commit on success, rollback on any
   exception. Writes are atomic; readers use WAL and are never blocked.

## Components

| Component | Location | Responsibility |
|---|---|---|
| ObjectStore | `backend/storage/object_store.py` | Physical file I/O per node; streaming writes; SHA-256; atomic rename; corruption injection |
| NodeManager | `backend/storage/node_manager.py` | Node lifecycle, status transitions, failure/partition/restore, counter sync |
| PlacementPolicy | `backend/storage/placement.py` | Chooses distinct healthy nodes, least-utilized first; enforces RF ≤ healthy nodes |
| ReplicaManager | `backend/replication/replica_manager.py` | Verified replica creation, read selection with round-robin, repair, migration |
| RepairManager/Queue | `backend/repair/` | De-duplicated job queue; atomic claim; verified execution; duration metrics |
| IntegrityVerifier | `backend/integrity/verifier.py` | SHA-256 expected-vs-actual per replica; object state machine; cluster scans |
| HealthChecker | `backend/health/health_checker.py` | Heartbeat refresh; timeout detection → FAILED |
| FailureDetector | `backend/health/failure_detector.py` | Objects below RF → schedule repairs (de-duplicated) |
| Rebalancer | `backend/rebalancing/rebalancer.py` | Plans and executes moves from over- to under-utilized nodes |
| Workers | `backend/workers/` | Async loops: health, repair, integrity, rebalance |
| Services | `backend/services/` | Upload/download/delete orchestration |
| API routers | `backend/api/` | HTTP surface, request validation, error mapping |

## Key data flows

### Upload

```
POST /api/files/upload
  → stream to temp file (never full-file in memory)
  → SHA-256(temp file)
  → placement: choose RF distinct healthy nodes (least utilized first)
  → for each node: write .tmp → fsync-rename → verify SHA-256 == expected
  → single transaction: INSERT object + RF replica rows + activity events
  → 200 with placement summary
```

A replica that fails verification never commits metadata; the write is rolled
back from disk and the upload fails loudly.

### Download (read path with failover)

```
GET /api/files/{id}/download
  → load metadata + healthy replicas (HEALTHY row ∧ node ONLINE ∧ CONNECTED)
  → rotate starting replica (round-robin read spreading)
  → read replica → SHA-256 → compare with metadata checksum
      ✓ match    → serve file, log OBJECT_DOWNLOADED
      ✗ mismatch → mark replica CORRUPTED, schedule repair, try next replica
  → no replicas verify → 409 object_unavailable (never serve corrupt data)
```

### Node failure → automatic repair

```
POST /api/nodes/{id}/fail
  → node: FAILED / DISCONNECTED; its HEALTHY replicas → UNAVAILABLE
  → metadata retained (nothing is deleted)
  → failure detector: objects below RF → repair jobs (de-duplicated)
  → repair worker (every REPAIR_INTERVAL seconds):
      claim job atomically (QUEUED → RUNNING)
      source node still down → copy verified replica to a new node,
                               delete dead replica row (REPLICA_DELETED)
      source node up        → rebuild in place from a healthy peer
      verify SHA-256 before COMPLETED; duration recorded
```

### Corruption detection → repair

```
bytes on disk diverge from metadata checksum (simulated or real)
  → verify_object() / cluster scan detects → replica CORRUPTED
  → repair job CHECKSUM_MISMATCH
  → repair copies from a healthy peer (which itself re-verifies)
  → checksum match → replica HEALTHY → object HEALTHY
```

## State machines

**Node**: `ONLINE ⇄ FAILED | PARTITIONED | RECOVERING | REBALANCING`
(transitions happen only through explicit `set_status` calls that write
activity/system events).

**Object**: `HEALTHY · DEGRADED · REPAIRING · CORRUPTED · UNAVAILABLE ·
REBALANCING` — recomputed from replica rows after verification and repair; no
status is ever guessed.

**Replica**: `HEALTHY · MISSING · CORRUPTED · STALE · REPAIRING · UNAVAILABLE`.

## Concurrency model

- **Reads** are lock-free: they read committed SQLite rows (WAL) and replica
  files; concurrent readers of the same object each get a unique staging file.
- **Writes** serialize on the SQLite write lock; per-object `LockManager`
  exists for coarser critical sections.
- **Repair jobs** de-duplicate inside the same transaction that inserts them,
  so concurrent schedulers cannot create duplicates; `claim_next_job` flips
  `QUEUED → RUNNING` atomically so two workers can never run one job.
- **Versioning**: objects carry a monotonic `version`; `check_version`
  implements optimistic concurrency and raises `409 version_conflict` on stale
  writes.

## Simulated independence

Each node is an isolated directory (`storage_nodes/nodeX/data/`). A failing
node means writes/reads to that directory are refused — other nodes are
untouched. The node registry, capacity, and status live in metadata, matching
what a real per-node daemon would report, so moving a node to a separate
process or machine later means replacing directory I/O in `ObjectStore` with
network calls — no other layer changes. See `docs/system-design.md`.

# VAULT — Recovery

## Repair workflow

```
trigger            de-duplicated enqueue (one active job per replica)
                       │  QUEUED
                       ▼  repair worker polls every REPAIR_INTERVAL s
claim              QUEUED → RUNNING   (atomic single-claimer)
                       │
execute            source node ONLINE → rebuild in place from healthy peer
                   source node down  → place on new node, retire dead replica
                       │
verify             SHA-256(stored bytes) == authoritative checksum
                       │
              ┌──────┴──────┐
              ▼             ▼
        COMPLETED        FAILED (error recorded; retry endpoint available)
        duration_ms
        recorded
```

Idempotency: enqueueing a repair for a replica that already has an active job
is a no-op; claiming a job that references a vanished replica skips cleanly;
re-running a completed repair for an already-healthy replica is skipped.

## Recovery metrics

Recorded per job and aggregated at `GET /api/repairs/metrics`:

| Metric | Source |
|---|---|
| Repair start / end | `started_at` / `completed_at` |
| Duration per repair | `duration_ms` |
| Average recovery time | `AVG(duration_ms)` over COMPLETED jobs |
| Failed nodes involved | `failed_node_id` |
| Repaired replicas | COMPLETED job count |
| Corrupted replicas | `GET /api/system/stats → corrupted_replicas` |
| Failed repairs | FAILED job count (each with logged error) |
| Currently active | QUEUED + RUNNING + VERIFYING |

The dashboard's Repair Center surfaces all of these live.

## Rebalancing

Triggered manually (`POST /api/rebalance`), from the dashboard, or by the
background worker when a node exceeds `rebalance_threshold` (default 80%).

```
plan     overloaded  = nodes above threshold
         targets     = HEALTHY replicas on overloaded nodes whose object
                       keeps >1 replica and whose object has no replica on
                       the destination
         destination = under-utilized node (below cluster average)
                       never already holding the object

move     write verified copy to destination → verify SHA-256
         → insert new replica row → delete source row → delete source file
         (verify-before-delete is enforced inside migrate_replica)
```

Recorded in `rebalance_jobs` (source, destination, bytes, status) and shown as
`node1 → node4` movements on the Rebalancing page. Source storage and
destination storage counters are synced after each move.

## Recovery-time tuning

| Knob | Effect |
|---|---|
| `REPAIR_INTERVAL` (default 5s) | how fast queued repairs execute |
| `HEALTH_CHECK_INTERVAL` (default 5s) | how fast failures are noticed (timeout = 3× interval) |
| `INTEGRITY_CHECK_INTERVAL` (default 30s) | background scan cadence for silent corruption |
| `REPLICATION_FACTOR` | higher RF = more parallel repair sources, more overhead |

## Zero-data-loss guarantees recap

- placement never co-locates replicas of one object
- repairs only use verified-healthy sources
- verification precedes every metadata commit and every source deletion
- failures never delete metadata; stale data is reconciled, not trusted

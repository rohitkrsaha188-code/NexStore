# VAULT — Replication

## Replication factor

- Configurable per upload (`?replication_factor=N`) and cluster-wide via
  Settings / `PUT /api/system/settings`.
- Constraint: `1 ≤ RF ≤ healthy node count`. Violations return
  `409 insufficient_healthy_nodes` — the system never pretends to replicate
  onto nodes that don't exist.
- Default: `REPLICATION_FACTOR=3` from `.env`.

## Placement strategy

`PlacementPolicy.choose_nodes(count, exclude)`:

1. Candidate set: `status=ONLINE ∧ network_status=CONNECTED ∧ health=HEALTHY`
2. Ordered by `used_capacity ASC` (least-utilized first), `node_id ASC` as tiebreaker
3. Exclude nodes already holding a replica of this object (strict uniqueness)
4. Take the first `count`; if fewer exist → `InsufficientNodesError` → 409

Properties:

- **No co-located replicas** — one node failure can never remove all copies
- **Load spreading** — new objects land on emptier nodes first
- **Failure-aware** — failed/partitioned nodes never receive fresh data

## Replica lifecycle

```
upload   → stage file on node → verify SHA-256 → commit row HEALTHY
failure  → node fails          → row UNAVAILABLE (metadata retained)
repair   → verified rebuild    → row HEALTHY (checksum re-verified)
migrate  → verified copy       → new row HEALTHY, source row deleted
delete   → files removed       → rows deleted
```

A replica row is only HEALTHY if its bytes on disk currently match the
authoritative checksum. Verification happens **before** metadata commits —
never after.

## Replica consistency

Each replica row stores `version` + `checksum` of the data it holds. The
**object row** is authoritative. `check_object_consistency(object_id)` reports:

- `stale_replicas` — version behind the authoritative version
- `divergent_replicas` — checksum differs from the authoritative checksum

Resolution rules (documented, not implicit):

1. **Newer wins.** The authoritative version is the cluster's truth; a stale
   replica is never promoted over it and never silently overwrites it.
2. **Verify, don't trust.** A replica reappearing after a partition is STALE.
   Reconciliation reads its *physical bytes* and recomputes SHA-256:
   - matches authoritative → HEALTHY again
   - mismatched → stays STALE → repair replaces it from a verified peer
3. **Never replicate corruption.** `create_replica` refuses to copy a source
   whose checksum doesn't match the authoritative metadata.

## Read path preference

`healthy_replicas(object_id)` = rows with `status=HEALTHY` on nodes that are
`ONLINE` and `CONNECTED`. Reads rotate their starting replica (round-robin) to
spread load. During a partition or failure, reads are served from any
remaining healthy replica; only when **zero** verify does the API return
`409 object_unavailable` — corrupted or incomplete data is never served as
valid.

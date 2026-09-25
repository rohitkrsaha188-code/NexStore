# VAULT — Failure Handling

## Failure classes

| Class | Node status | Data | Metadata | Detection |
|---|---|---|---|---|
| Crash / hardware death | `FAILED` (DISCONNECTED) | intact on disk | retained | simulated via API or heartbeat timeout |
| Network partition | `PARTITIONED` (PARTITIONED) | intact, unreachable | retained | simulated via API |
| Silent corruption | node stays ONLINE | **bytes diverge** | retained | SHA-256 verification |
| Replica loss | any | file missing | row remains | file-not-found / scan |

The system deliberately distinguishes **FAILED** (presumed long-term loss;
replace the replica elsewhere) from **PARTITIONED** (temporarily unreachable;
keep metadata, reconcile on reconnect). Neither deletes anything.

## Node failure workflow

```
POST /api/nodes/node2/fail
 1. node2 → FAILED / DISCONNECTED          (activity: NODE_FAILED)
 2. node2's HEALTHY replicas → UNAVAILABLE (files untouched)
 3. failure detector: for each object below RF → repair jobs
    (insert + dedup in one transaction — no duplicates)
 4. repair worker claims a job:
      source node ONLINE?  → rebuild replica in place from a healthy peer
      source node down?    → copy to a NEW node, retire the dead replica row
 5. verify SHA-256 of the rebuilt copy
      ✓ → replica HEALTHY, job COMPLETED (duration recorded)
      ✗ → job FAILED (retriable via POST /api/repairs/{id}/retry)
 6. object status recomputed → HEALTHY when RF satisfied again

Before:  node1 ✓  node2 ✗  node3 ✓          object DEGRADED
After:   node1 ✓  node2 ✗  node3 ✓  node4 ✓  object HEALTHY
```

## Network partition workflow

```
POST /api/nodes/node4/partition
 1. node4 → PARTITIONED; replicas UNAVAILABLE; metadata + files retained
 2. reads continue from remaining healthy replicas (no 409 while RF-1 exist)
 3. writes avoid node4 (placement excludes non-ONLINE nodes)

POST /api/nodes/node4/reconnect
 4. node4 → ONLINE; its UNAVAILABLE replicas → STALE (candidates, not truth)
 5. reconciliation verifies physical bytes:
      checksum matches metadata → replica HEALTHY
      corrupted while unreachable → stays STALE → repair replaces it
```

## Silent corruption workflow

```
bytes on node3 diverge from metadata (simulated via
POST /api/files/{id}/corrupt or a real bit-rot)
 1. verification (on-demand, download path, or background scan) recomputes
    SHA-256 → CHECKSUM MISMATCH      (activity: CORRUPTION_DETECTED)
 2. replica → CORRUPTED; repair job CHECKSUM_MISMATCH queued
 3. repair reads a HEALTHY peer (re-verifying the source!), rewrites node3
 4. re-verify → HEALTHY

Dashboard shows:  ⚠ CHECKSUM MISMATCH → REPAIRING → ✓ VERIFIED
```

## Unavailability

If **all** replicas of an object are lost or fail verification, the object is
`UNAVAILABLE` and the API returns `409 object_unavailable`. VAULT will never
serve unverified bytes as valid data.

## What is never done

- Metadata is never destroyed because a node failed
- A corrupted replica is never used as a repair source
- A newer version is never overwritten by a stale replica
- A source replica is never deleted before the destination verifies
  (rebalancing and repair both follow verify-before-delete)
- Failures are never swallowed — every transition writes an activity and a
  system event, and logs at WARNING/ERROR

# VAULT — System Design

## Design goals

1. Fault tolerance against independently failing nodes
2. No silent data loss: verify everything, trust nothing
3. Predictable availability through replication
4. Observable recovery (metrics, events, dashboards)
5. Local runnability with a clear path to real distribution

## The simulated distributed environment

Five storage nodes run on one machine as **logically independent** directories:

```
storage_nodes/node1/data/    ← objects as {object_id}.v{version}
storage_nodes/node2/data/
storage_nodes/node3/data/
storage_nodes/node4/data/
storage_nodes/node5/data/
```

What makes them *independent* and not just folders:

- Node identity, capacity, status, and heartbeat live in the node registry
  (metadata), exactly as a real node daemon would report them.
- All reads/writes of object bytes go through `ObjectStore` keyed by
  `node_id`. No other component knows the directory layout.
- Failure semantics are per-node: a FAILED node refuses reads/writes while
  its files remain intact on disk — the same observable behavior as a dead
  machine with persistent disks.

### Path to real distribution

To move a node to a separate process/machine:

1. Run one `node_agent` process per machine exposing
   `PUT/GET/DELETE /objects/{id}` plus `GET /health`.
2. Re-implement `ObjectStore`'s five methods as HTTP calls to the agent.
3. Replace `heartbeat` DB updates with the agent's liveness responses.

Every other layer (placement, repair, integrity, rebalancing, API, UI) is
unchanged because it already treats nodes as opaque remote peers.

## Metadata schema (SQLite)

| Table | Purpose |
|---|---|
| `nodes` | Registry: status, network status, capacity, counters, heartbeat |
| `objects` | Logical objects: size, content type, checksum, version, RF, status |
| `replicas` | Physical placement: object × node, checksum, version, size, status |
| `repair_jobs` | Queue + history: reason, nodes, status, progress, duration |
| `rebalance_jobs` | Movement history: source → destination, bytes moved |
| `activity_logs` | User-visible event feed |
| `system_events` | Severity-tagged system journal |
| `settings` | Runtime-tunable cluster configuration |

Object bytes are **never** stored in SQLite — only under node directories.

## Placement strategy

Greedy least-utilized with strict node uniqueness per object:

```
candidates = nodes WHERE status=ONLINE AND network=CONNECTED AND health=HEALTHY
             ORDER BY used_capacity ASC
chosen     = first RF candidates not already holding a replica of the object
raise InsufficientNodesError if fewer than RF available  (409 to the client)
```

Rationale: cheap to compute, spreads load, and the uniqueness constraint
guarantees single-node failures never remove all replicas.

## Versioning strategy

- The **object row** holds the authoritative `version` and `checksum`.
- Every replica row records the `version` and `checksum` it stores.
- Authoritative = the object row. Replicas are compared against it — never
  against each other and never against client-supplied values.
- A replica whose version is behind is **STALE**; a replica whose checksum
  differs is **CORRUPTED**. Both are repaired from a verified-healthy peer.
- Writes use optimistic concurrency: `check_version(object_id, provided)`
  raises `409 version_conflict` when the client's copy is out of date, so a
  lost-update can never silently overwrite newer data.

## Recovery

RTO (recovery time) is minimized by:

- background repair worker polling every `REPAIR_INTERVAL` seconds
- repairs verify-then-commit; a repair either restores a healthy replica or
  fails loudly (never half-done)
- node replacement: when a failed node stays down, the worker places the
  replica on a fresh node and retires the dead replica row, restoring RF

RPO (data loss) is zero for any single-node failure because placement never
co-locates replicas, and repairs never trust an unverified source.

Storage overhead is exactly `RF × logical size` while healthy, reported live
on the dashboard (logical vs physical vs overhead).

## Observability

- `activity_logs` power the live feed and event log
- `repair_jobs` yield active/completed/failed counts and **average recovery
  time** (mean duration of completed repairs)
- `/api/system/stats` aggregates cluster health, storage, and repair metrics
- `system_events` record severity-tagged state transitions for auditing
- structured `logging` to stdout and `data/logs/vault.log` (rotating)

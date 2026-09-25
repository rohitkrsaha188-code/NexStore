"""Corruption simulation: flip bytes in a stored replica, keep metadata intact."""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow
from backend.exceptions import ReplicaNotFoundError
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.corruption")


def corrupt_replica(store: ObjectStore, replica_id: str) -> dict:
    """Physically modify a replica on disk. The metadata checksum stays the
    original so the next verification detects CHECKSUM MISMATCH."""
    replica = db.query_one("SELECT * FROM replicas WHERE replica_id=?", (replica_id,))
    if replica is None:
        raise ReplicaNotFoundError(f"Unknown replica: {replica_id}")
    node = db.query_one("SELECT status FROM nodes WHERE node_id=?", (replica["node_id"],))
    if node and node["status"] != "ONLINE":
        raise ValueError(f"Node {replica['node_id']} is not ONLINE; cannot corrupt")

    ok = store.corrupt_replica(replica["node_id"], replica["object_id"], replica["version"])
    if not ok:
        raise ValueError(f"Replica {replica_id} has no stored bytes to corrupt")

    with db.write() as conn:
        conn.execute(
            "UPDATE replicas SET status='CORRUPTED', updated_at=? WHERE replica_id=?",
            (utcnow(), replica_id),
        )
        log_activity(
            conn, "CORRUPTION_SIMULATED",
            f"Corruption injected on {replica['node_id']} ({replica['object_id']})",
            object_id=replica["object_id"], node_id=replica["node_id"],
        )
    logger.warning("Corruption simulated on replica %s", replica_id)
    return {"replica_id": replica_id, "node_id": replica["node_id"], "object_id": replica["object_id"]}

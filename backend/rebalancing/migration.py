"""Migration helper for rebalancing moves."""
from __future__ import annotations

from backend.database import db, log_activity, utcnow
from backend.replication.replica_manager import ReplicaManager


def run_migration(replicas: ReplicaManager, *, replica_id: str, dest_node_id: str,
                  job_id: str) -> dict:
    """Execute a single replica move and update the rebalance_jobs row."""
    replica = db.query_one("SELECT * FROM replicas WHERE replica_id=?", (replica_id,))
    if replica is None:
        with db.write() as conn:
            conn.execute(
                "UPDATE rebalance_jobs SET status='FAILED', completed_at=?, error='replica missing' "
                "WHERE job_id=?",
                (utcnow(), job_id),
            )
        return {"job_id": job_id, "status": "FAILED"}
    with db.write() as conn:
        conn.execute(
            "UPDATE rebalance_jobs SET status='RUNNING', started_at=? WHERE job_id=?",
            (utcnow(), job_id),
        )
    try:
        new_replica = replicas.migrate_replica(replica_id, dest_node_id)
    except Exception as exc:  # noqa: BLE001
        with db.write() as conn:
            conn.execute(
                "UPDATE rebalance_jobs SET status='FAILED', completed_at=?, error=? WHERE job_id=?",
                (utcnow(), str(exc), job_id),
            )
        return {"job_id": job_id, "status": "FAILED", "error": str(exc)}

    with db.write() as conn:
        conn.execute(
            "UPDATE rebalance_jobs SET status='COMPLETED', progress=100, bytes_moved=?, "
            "completed_at=? WHERE job_id=?",
            (new_replica["size"], utcnow(), job_id),
        )
        log_activity(
            conn, "REBALANCE_COMPLETED",
            f"Replica moved {replica['node_id']} -> {dest_node_id}",
            object_id=replica["object_id"], node_id=dest_node_id,
        )
    return {"job_id": job_id, "status": "COMPLETED", "bytes_moved": new_replica["size"]}

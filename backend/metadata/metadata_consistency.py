"""Metadata consistency sweep: detect orphans and phantom replicas."""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow

logger = logging.getLogger("vault.metadata_consistency")


def run_consistency_sweep() -> dict:
    """Fix drift between metadata and reality; safe to run repeatedly."""
    orphans = db.query_all(
        """
        SELECT r.replica_id FROM replicas r
        LEFT JOIN objects o ON o.object_id = r.object_id
        WHERE o.object_id IS NULL
        """
    )
    removed = 0
    with db.write() as conn:
        for row in orphans:
            conn.execute("DELETE FROM replicas WHERE replica_id=?", (row["replica_id"],))
            removed += 1

    # Replicas whose node no longer exists (node registry is immutable in the sim).
    phantom_nodes = db.query_all(
        """
        SELECT r.replica_id, r.node_id FROM replicas r
        LEFT JOIN nodes n ON n.node_id = r.node_id
        WHERE n.node_id IS NULL
        """
    )
    with db.write() as conn:
        for row in phantom_nodes:
            conn.execute("DELETE FROM replicas WHERE replica_id=?", (row["replica_id"],))
            removed += 1

    # Queued repairs referencing deleted objects should never run.
    stale_jobs = db.query_all(
        """
        SELECT j.repair_id FROM repair_jobs j
        LEFT JOIN objects o ON o.object_id = j.object_id
        WHERE o.object_id IS NULL AND j.status IN ('QUEUED','RUNNING','VERIFYING')
        """
    )
    with db.write() as conn:
        for row in stale_jobs:
            conn.execute(
                "UPDATE repair_jobs SET status='CANCELLED', completed_at=?, error='object deleted' "
                "WHERE repair_id=?",
                (utcnow(), row["repair_id"]),
            )
    if removed or stale_jobs:
        logger.info("Consistency sweep: removed=%d cancelled_jobs=%d", removed, len(stale_jobs))
    return {"orphan_replicas_removed": removed, "stale_jobs_cancelled": len(stale_jobs)}

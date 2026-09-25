"""Failure detection: translate node loss into repair work."""
from __future__ import annotations

import logging

from backend.database import db
from backend.repair.repair_manager import RepairManager

logger = logging.getLogger("vault.failure_detector")


def detect_degraded_objects() -> list[dict]:
    """Find objects below their replication factor and schedule repairs.

    Called by the health worker after a node failure is detected. Repair jobs
    are de-duplicated so a repeated scan does not queue duplicate work.
    """
    rows = db.query_all(
        """
        SELECT o.object_id, o.replication_factor, o.filename,
               COUNT(r.replica_id) AS have,
               SUM(CASE WHEN r.status='HEALTHY' AND n.status='ONLINE'
                         AND n.network_status='CONNECTED' THEN 1 ELSE 0 END) AS healthy
        FROM objects o
        LEFT JOIN replicas r ON r.object_id = o.object_id
        LEFT JOIN nodes n ON n.node_id = r.node_id
        GROUP BY o.object_id
        """
    )
    scheduled: list[dict] = []
    for row in rows:
        deficit = row["replication_factor"] - (row["healthy"] or 0)
        if deficit <= 0:
            continue
        manager = RepairManager.instance()
        missing = manager.schedule_missing_replicas(
            object_id=row["object_id"], desired=row["replication_factor"]
        )
        for replica_id in missing:
            scheduled.append({"object_id": row["object_id"], "replica_id": replica_id})
        if missing:
            logger.info(
                "Object %s degraded (%d/%d healthy): queued %d repair job(s)",
                row["object_id"], row["healthy"] or 0, row["replication_factor"], len(missing),
            )
    return scheduled

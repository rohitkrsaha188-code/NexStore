"""Repair queue backed by the repair_jobs table.

De-duplication: one active job per replica. Claiming flips QUEUED -> RUNNING
atomically so concurrent workers cannot run the same job twice.
"""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow

logger = logging.getLogger("vault.repair_queue")


def enqueue_repair(
    *, object_id: str, replica_id: str, reason: str, failed_node_id: str | None
) -> str | None:
    """Create a repair job unless one is already active for the replica.

    The dedup check and insert run in one serialized write transaction, so
    concurrent schedulers can never queue two jobs for the same replica.
    """
    with db.write() as conn:
        existing = conn.execute(
            "SELECT repair_id FROM repair_jobs WHERE replica_id=? AND status IN ('QUEUED','RUNNING','VERIFYING')",
            (replica_id,),
        ).fetchone()
        if existing:
            return None  # idempotent: no duplicate repair jobs
        repair_id = f"repjob_{object_id}_{replica_id.rsplit('_', 1)[-1]}_{utcnow()[-8:].replace(':', '')}"
        conn.execute(
            "INSERT INTO repair_jobs(repair_id, object_id, replica_id, failed_node_id, reason, "
            "status, progress, created_at) VALUES(?,?,?,?,?,?,0,?)",
            (repair_id, object_id, replica_id, failed_node_id, reason, "QUEUED", utcnow()),
        )
        log_activity(
            conn, "REPAIR_STARTED", f"Repair queued for {object_id} on {failed_node_id or 'missing replica'}",
            object_id=object_id, node_id=failed_node_id,
        )
    logger.info("Repair queued: %s", repair_id)
    return repair_id


def claim_next_job() -> dict | None:
    """Atomically claim the oldest queued job."""
    with db.write() as conn:
        row = conn.execute(
            "SELECT * FROM repair_jobs WHERE status='QUEUED' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        job = dict(row)
        conn.execute(
            "UPDATE repair_jobs SET status='RUNNING', started_at=?, progress=10 WHERE repair_id=?",
            (utcnow(), job["repair_id"]),
        )
    job["status"] = "RUNNING"
    job["progress"] = 10
    return job


def finish_job(repair_id: str, *, status: str, progress: int, error: str | None = None,
               duration_ms: int | None = None) -> None:
    with db.write() as conn:
        conn.execute(
            "UPDATE repair_jobs SET status=?, progress=?, completed_at=?, duration_ms=?, error=? "
            "WHERE repair_id=?",
            (status, progress, utcnow(), duration_ms, error, repair_id),
        )
        event = {
            "COMPLETED": "REPAIR_COMPLETED",
            "FAILED": "REPAIR_FAILED",
        }.get(status)
        if event:
            log_activity(conn, event, f"Repair {repair_id} -> {status}", object_id=None)
    logger.info("Repair %s -> %s", repair_id, status)


def set_progress(repair_id: str, progress: int, status: str | None = None) -> None:
    with db.write() as conn:
        if status:
            conn.execute(
                "UPDATE repair_jobs SET progress=?, status=? WHERE repair_id=?",
                (progress, status, repair_id),
            )
        else:
            conn.execute(
                "UPDATE repair_jobs SET progress=? WHERE repair_id=?", (progress, repair_id)
            )

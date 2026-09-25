"""Repair endpoints: list jobs, retry failed jobs, repair metrics."""
from __future__ import annotations

from fastapi import APIRouter

from backend.database import db, log_activity, utcnow
from backend.exceptions import NotFoundError
from backend.schemas import RepairJobOut

router = APIRouter(prefix="/api/repairs", tags=["repairs"])


def _with_filename(job: dict) -> dict:
    obj = db.query_one("SELECT filename FROM objects WHERE object_id=?", (job["object_id"],))
    return {**job, "filename": obj["filename"] if obj else "(deleted)"}


@router.get("", response_model=list[RepairJobOut])
def list_repairs(status: str | None = None, limit: int = 100) -> list[dict]:
    if status:
        rows = db.query_all(
            "SELECT * FROM repair_jobs WHERE status=? ORDER BY created_at DESC LIMIT ?",
            (status, min(limit, 500)),
        )
    else:
        rows = db.query_all(
            "SELECT * FROM repair_jobs ORDER BY created_at DESC LIMIT ?", (min(limit, 500),)
        )
    return [_with_filename(row) for row in rows]


@router.post("/{repair_id}/retry")
def retry_repair(repair_id: str) -> dict:
    job = db.query_one("SELECT * FROM repair_jobs WHERE repair_id=?", (repair_id,))
    if job is None:
        raise NotFoundError(f"Unknown repair job: {repair_id}")
    if job["status"] not in ("FAILED", "COMPLETED"):
        return {"repair_id": repair_id, "status": job["status"], "message": "Job is already active"}

    # Re-queue only if the replica still needs help.
    replica = db.query_one("SELECT * FROM replicas WHERE replica_id=?", (job["replica_id"],))
    if replica is None:
        return {"repair_id": repair_id, "status": "OBSOLETE",
                "message": "Replica row no longer exists; nothing to repair"}
    with db.write() as conn:
        conn.execute(
            "INSERT INTO repair_jobs(repair_id, object_id, replica_id, failed_node_id, reason, "
            "status, progress, created_at) VALUES(?,?,?,?,?,'QUEUED',0,?)",
            (f"{repair_id}_retry{utcnow()[-6:]}", job["object_id"], job["replica_id"],
             job["failed_node_id"], "RETRY", utcnow()),
        )
        log_activity(conn, "REPAIR_QUEUED", f"Repair re-queued: {repair_id}", object_id=job["object_id"])
    from backend.repair.repair_manager import RepairManager

    RepairManager.instance().run_pending_repairs(max_jobs=1)
    new_job = db.query_one(
        "SELECT * FROM repair_jobs WHERE repair_id LIKE ? ORDER BY created_at DESC LIMIT 1",
        (f"{repair_id}%",),
    )
    return {"repair_id": new_job["repair_id"] if new_job else repair_id,
            "status": new_job["status"] if new_job else "UNKNOWN"}


@router.get("/metrics")
def repair_metrics() -> dict:
    def count(status: str | None) -> int:
        if status is None:
            return db.scalar("SELECT COUNT(*) FROM repair_jobs") or 0
        return db.scalar("SELECT COUNT(*) FROM repair_jobs WHERE status=?", (status,)) or 0

    avg = db.scalar(
        "SELECT AVG(duration_ms) FROM repair_jobs WHERE status='COMPLETED' AND duration_ms IS NOT NULL"
    )
    return {
        "total": count(None),
        "queued": count("QUEUED"),
        "running": count("RUNNING") + count("VERIFYING"),
        "completed": count("COMPLETED"),
        "failed": count("FAILED"),
        "avg_recovery_ms": int(avg) if avg is not None else None,
    }

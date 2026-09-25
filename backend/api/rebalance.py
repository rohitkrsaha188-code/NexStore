"""Rebalance endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import get_replica_manager
from backend.database import get_setting_int
from backend.rebalancing.rebalancer import execute_rebalance, plan_rebalance, rebalance_status
from backend.schemas import RebalanceJobOut

router = APIRouter(prefix="/api/rebalance", tags=["rebalance"])


@router.post("")
def trigger_rebalance(max_moves: int = 5) -> dict:
    threshold = get_setting_int("rebalance_threshold", 80)
    return execute_rebalance(get_replica_manager(), threshold, max_moves=max_moves)


@router.get("/plan")
def rebalance_plan() -> dict:
    threshold = get_setting_int("rebalance_threshold", 80)
    moves = plan_rebalance(threshold)
    return {"threshold": threshold, "planned_moves": moves}


@router.get("/status")
def status() -> dict:
    return rebalance_status()


@router.get("/jobs", response_model=list[RebalanceJobOut])
def jobs(limit: int = 100) -> list[dict]:
    from backend.database import db

    rows = db.query_all(
        "SELECT * FROM rebalance_jobs ORDER BY created_at DESC LIMIT ?", (min(limit, 500),)
    )
    out = []
    for row in rows:
        obj = db.query_one("SELECT filename FROM objects WHERE object_id=?", (row["object_id"],))
        out.append({**row, "filename": obj["filename"] if obj else "(deleted)"})
    return out

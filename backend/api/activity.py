"""Activity endpoints: recent event feed for the dashboard."""
from __future__ import annotations

from fastapi import APIRouter

from backend.database import db
from backend.schemas import ActivityOut

router = APIRouter(prefix="/api/activity", tags=["activity"])


@router.get("", response_model=list[ActivityOut])
def recent_activity(limit: int = 100) -> list[dict]:
    rows = db.query_all(
        "SELECT * FROM activity_logs ORDER BY id DESC LIMIT ?", (min(limit, 500),)
    )
    return rows

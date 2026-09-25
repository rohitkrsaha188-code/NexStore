"""Health API: detailed per-node health and manual check trigger."""
from __future__ import annotations

from fastapi import APIRouter

from backend.database import db, get_setting_int
from backend.health.health_checker import run_health_check
from backend.schemas import HealthResponse

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/detailed")
def detailed_health() -> dict:
    nodes = db.query_all("SELECT * FROM nodes ORDER BY node_id")
    objects = db.query_all("SELECT status, COUNT(*) AS n FROM objects GROUP BY status")
    replicas = db.query_all("SELECT status, COUNT(*) AS n FROM replicas GROUP BY status")
    return {
        "nodes": [
            {
                "node_id": n["node_id"], "status": n["status"],
                "network_status": n["network_status"], "health_status": n["health_status"],
                "last_heartbeat": n["last_heartbeat"],
            }
            for n in nodes
        ],
        "object_status_counts": {r["status"]: r["n"] for r in objects},
        "replica_status_counts": {r["status"]: r["n"] for r in replicas},
    }


@router.post("/check")
def trigger_health_check() -> dict:
    timeout = get_setting_int("health_check_interval", 5) * 3
    return run_health_check(heartbeat_timeout=timeout)

"""System endpoints: health, stats, settings."""
from __future__ import annotations

from fastapi import APIRouter

from backend.database import db, get_setting_int, set_setting
from backend.schemas import HealthResponse, SettingsOut, SettingsUpdate, SystemStats
from backend.storage.storage_metrics import storage_metrics

router = APIRouter(tags=["system"])


def _system_stats() -> dict:
    metrics = storage_metrics()
    nodes = db.query_all("SELECT status FROM nodes")
    online = len([n for n in nodes if n["status"] == "ONLINE"])
    failed = len([n for n in nodes if n["status"] == "FAILED"])
    partitioned = len([n for n in nodes if n["status"] == "PARTITIONED"])

    total_objects = db.scalar("SELECT COUNT(*) FROM objects") or 0
    total_replicas = db.scalar("SELECT COUNT(*) FROM replicas") or 0
    active_repairs = db.scalar(
        "SELECT COUNT(*) FROM repair_jobs WHERE status IN ('QUEUED','RUNNING','VERIFYING')"
    ) or 0
    completed = db.scalar(
        "SELECT COUNT(*) FROM repair_jobs WHERE status='COMPLETED'"
    ) or 0
    failed_repairs = db.scalar("SELECT COUNT(*) FROM repair_jobs WHERE status='FAILED'") or 0
    avg_repair_ms = db.scalar(
        "SELECT AVG(duration_ms) FROM repair_jobs WHERE status='COMPLETED' AND duration_ms IS NOT NULL"
    )
    corrupted = db.scalar("SELECT COUNT(*) FROM replicas WHERE status='CORRUPTED'") or 0

    if failed + partitioned >= max(1, len(nodes) - 1):
        status = "CRITICAL"
    elif failed or partitioned or active_repairs or corrupted:
        status = "DEGRADED"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "app_name": db.get_setting("app_name", "NexStore") or "NexStore",
        **metrics,
        "replication_factor": get_setting_int("replication_factor", 3),
        "total_objects": total_objects,
        "total_replicas": total_replicas,
        "nodes_total": len(nodes),
        "nodes_online": online,
        "nodes_failed": failed,
        "nodes_partitioned": partitioned,
        "active_repair_jobs": active_repairs,
        "completed_repairs": completed,
        "failed_repairs": failed_repairs,
        "avg_repair_ms": int(avg_repair_ms) if avg_repair_ms is not None else None,
        "corrupted_replicas": corrupted,
        "system_health": status,
    }


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    nodes = db.query_all("SELECT status FROM nodes")
    healthy = len([n for n in nodes if n["status"] == "ONLINE"])
    failed = len([n for n in nodes if n["status"] in ("FAILED", "PARTITIONED")])
    status = "healthy" if failed == 0 and healthy == len(nodes) and nodes else "degraded"
    return HealthResponse(
        status=status, nodes=len(nodes), healthy_nodes=healthy, failed_nodes=failed
    )


@router.get("/api/system/stats", response_model=SystemStats)
def system_stats() -> SystemStats:
    return SystemStats(**_system_stats())


@router.get("/api/system/settings", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    return SettingsOut(
        replication_factor=get_setting_int("replication_factor", 3),
        health_check_interval=get_setting_int("health_check_interval", 5),
        repair_interval=get_setting_int("repair_interval", 5),
        integrity_check_interval=get_setting_int("integrity_check_interval", 30),
        rebalance_threshold=get_setting_int("rebalance_threshold", 80),
        max_storage_per_node=get_setting_int("max_storage_per_node", 10 * 1024**3),
    )


@router.put("/api/system/settings", response_model=SettingsOut)
def update_settings(payload: SettingsUpdate) -> SettingsOut:
    updates = payload.model_dump(exclude_none=True)
    for key, value in updates.items():
        set_setting(key, str(value))
    return get_settings()


@router.get("/api/system/metrics")
def raw_metrics() -> dict:
    return storage_metrics()


@router.get("/api/system/events")
def system_events(limit: int = 50) -> dict:
    rows = db.query_all(
        "SELECT * FROM system_events ORDER BY id DESC LIMIT ?", (min(limit, 500),)
    )
    return {"events": rows}

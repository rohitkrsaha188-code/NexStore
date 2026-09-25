"""Storage metrics: logical vs physical usage and per-node utilization."""
from __future__ import annotations

from backend.database import db


def storage_metrics() -> dict:
    logical = db.scalar(
        "SELECT COALESCE(SUM(size), 0) FROM objects WHERE status != 'DELETED'"
    ) or 0
    physical = db.scalar(
        "SELECT COALESCE(SUM(size), 0) FROM replicas WHERE status IN ('HEALTHY','STALE','REPAIRING')"
    ) or 0
    nodes = db.query_all(
        "SELECT node_id, name, capacity, used_capacity, status FROM nodes ORDER BY node_id"
    )
    total_capacity = sum(n["capacity"] for n in nodes)
    used = sum(n["used_capacity"] for n in nodes)
    return {
        "logical_storage": logical,
        "physical_storage": physical,
        "replication_overhead": max(0, physical - logical),
        "total_capacity": total_capacity,
        "used_capacity": used,
        "available_capacity": max(0, total_capacity - used),
        "per_node": [
            {
                "node_id": n["node_id"],
                "name": n["name"],
                "capacity": n["capacity"],
                "used_capacity": n["used_capacity"],
                "utilization": round(100 * n["used_capacity"] / n["capacity"], 2) if n["capacity"] else 0.0,
                "status": n["status"],
            }
            for n in nodes
        ],
    }

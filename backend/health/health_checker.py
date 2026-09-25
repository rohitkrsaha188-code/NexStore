"""Periodic health checks for the node fleet."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.database import db, log_activity, utcnow
from backend.health.heartbeat import touch_all_heartbeats

logger = logging.getLogger("vault.health_checker")


def _age_seconds(iso_ts: str) -> float:
    try:
        then = datetime.fromisoformat(iso_ts)
        return (datetime.now(timezone.utc) - then).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def run_health_check(heartbeat_timeout: int) -> dict:
    """Refresh heartbeats, evaluate timeouts, and flag failed nodes."""
    touch_all_heartbeats()
    nodes = db.query_all("SELECT * FROM nodes")
    timed_out: list[str] = []
    for node in nodes:
        age = _age_seconds(node["last_heartbeat"])
        if node["status"] in ("ONLINE", "RECOVERING") and age > heartbeat_timeout:
            timed_out.append(node["node_id"])
    for node_id in timed_out:
        with db.write() as conn:
            conn.execute(
                "UPDATE nodes SET status='FAILED', network_status='DISCONNECTED', updated_at=? "
                "WHERE node_id=? AND status IN ('ONLINE','RECOVERING')",
                (utcnow(), node_id),
            )
            conn.execute(
                "UPDATE replicas SET status='UNAVAILABLE', updated_at=? "
                "WHERE node_id=? AND status='HEALTHY'",
                (utcnow(), node_id),
            )
            log_activity(conn, "NODE_FAILED", f"Heartbeat timeout: {node_id} -> FAILED", node_id=node_id)
        logger.warning("Node %s heartbeat timeout -> FAILED", node_id)
    return {
        "checked": len(nodes),
        "online": len([n for n in nodes if n["status"] == "ONLINE"]),
        "failed": len([n for n in nodes if n["status"] == "FAILED"]),
        "timed_out": timed_out,
    }

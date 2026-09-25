"""Object query service: listing and detail assembly for the API layer."""
from __future__ import annotations

from backend.database import db
from backend.exceptions import ObjectNotFoundError


def list_objects() -> list[dict]:
    rows = db.query_all(
        """
        SELECT o.*, COUNT(r.replica_id) AS replica_count,
               SUM(CASE WHEN r.status='HEALTHY' THEN 1 ELSE 0 END) AS healthy_replicas
        FROM objects o
        LEFT JOIN replicas r ON r.object_id = o.object_id
        GROUP BY o.object_id
        ORDER BY o.created_at DESC
        """
    )
    out = []
    for row in rows:
        item = dict(row)
        required = row["replication_factor"]
        item["required_replicas"] = required
        item["healthy_replicas"] = row["healthy_replicas"] or 0
        item["missing_replicas"] = max(0, required - (row["healthy_replicas"] or 0))
        out.append(item)
    return out


def get_object_detail(object_id: str) -> dict:
    obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
    if obj is None:
        raise ObjectNotFoundError(f"Unknown object: {object_id}")
    replicas = db.query_all(
        "SELECT r.*, n.name AS node_name FROM replicas r JOIN nodes n ON n.node_id=r.node_id "
        "WHERE r.object_id=? ORDER BY r.node_id",
        (object_id,),
    )
    healthy = len([r for r in replicas if r["status"] == "HEALTHY"])
    required = obj["replication_factor"]
    return {
        **obj,
        "replica_count": len(replicas),
        "healthy_replicas": healthy,
        "required_replicas": required,
        "missing_replicas": max(0, required - healthy),
        "replicas": replicas,
    }

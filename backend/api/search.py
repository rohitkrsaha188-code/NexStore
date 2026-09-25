"""Global search across nodes, objects, repairs, and activity."""
from __future__ import annotations

from fastapi import APIRouter, Query

from backend.database import db

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def global_search(q: str = Query(..., min_length=1, max_length=120)) -> dict:
    term = f"%{q.strip()}%"
    results: list[dict] = []

    for row in db.query_all(
        "SELECT node_id, name, status, utilization, replica_count FROM nodes "
        "WHERE node_id LIKE ? OR name LIKE ? LIMIT 5",
        (term, term),
    ):
        results.append({
            "type": "node", "id": row["node_id"], "title": row["name"],
            "subtitle": f"{row['status']} · {row['replica_count']} replicas · {row['utilization']:.1f}%",
            "view": "nodes", "ref": row["node_id"],
        })

    for row in db.query_all(
        "SELECT object_id, filename, size, status, replication_factor FROM objects "
        "WHERE object_id LIKE ? OR filename LIKE ? ORDER BY updated_at DESC LIMIT 8",
        (term, term),
    ):
        results.append({
            "type": "object", "id": row["object_id"], "title": row["filename"],
            "subtitle": f"{row['size']} bytes · {row['status']} · RF={row['replication_factor']}",
            "view": "objects", "ref": row["object_id"],
        })

    for row in db.query_all(
        "SELECT repair_id, object_id, filename, status, failed_node_id FROM repair_jobs "
        "WHERE repair_id LIKE ? OR object_id LIKE ? OR filename LIKE ? "
        "ORDER BY created_at DESC LIMIT 5",
        (term, term, term),
    ):
        results.append({
            "type": "repair", "id": row["repair_id"], "title": row["filename"] or row["object_id"],
            "subtitle": f"repair {row['status']} · failed on {row['failed_node_id'] or '—'}",
            "view": "repairs", "ref": row["repair_id"],
        })

    for row in db.query_all(
        "SELECT id, event_type, message, created_at FROM activity_logs "
        "WHERE event_type LIKE ? OR message LIKE ? ORDER BY id DESC LIMIT 6",
        (term, term),
    ):
        results.append({
            "type": "activity", "id": str(row["id"]), "title": row["event_type"],
            "subtitle": row["message"][:100], "view": "activity", "ref": None,
        })

    return {"query": q, "results": results}

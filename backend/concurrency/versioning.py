"""Optimistic concurrency: version checks for object updates."""
from __future__ import annotations

from backend.database import db
from backend.exceptions import VersionConflictError


def check_version(object_id: str, provided_version: int | None) -> int:
    """Return current version; raise 409 when the client's copy is stale."""
    obj = db.query_one("SELECT version FROM objects WHERE object_id=?", (object_id,))
    if obj is None:
        return 0
    if provided_version is not None and provided_version != obj["version"]:
        raise VersionConflictError(
            f"Version conflict for {object_id}: current={obj['version']}, provided={provided_version}"
        )
    return obj["version"]


def bump_version(object_id: str) -> int:
    with db.write() as conn:
        conn.execute(
            "UPDATE objects SET version = version + 1, updated_at = ? WHERE object_id=?",
            (utcnow_str(), object_id),
        )
    row = db.query_one("SELECT version FROM objects WHERE object_id=?", (object_id,))
    return row["version"] if row else 0


def utcnow_str() -> str:
    from backend.database import utcnow

    return utcnow()

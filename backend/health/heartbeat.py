"""Heartbeat updates for simulated storage nodes."""
from __future__ import annotations

from backend.database import db, utcnow


def touch_all_heartbeats() -> None:
    """Simulated nodes heartbeat from inside the vault process."""
    with db.write() as conn:
        conn.execute(
            "UPDATE nodes SET last_heartbeat=?, updated_at=? WHERE status='ONLINE'",
            (utcnow(), utcnow()),
        )

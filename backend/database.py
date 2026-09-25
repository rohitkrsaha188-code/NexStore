"""SQLite access layer: schema, connections, and small query helpers.

A single connection is reused per thread (FastAPI runs sync endpoints in a
threadpool). WAL mode allows concurrent readers while a lock serializes
writers so metadata updates stay atomic.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from backend.config import settings

logger = logging.getLogger("vault.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ONLINE',
    health_status TEXT NOT NULL DEFAULT 'HEALTHY',
    network_status TEXT NOT NULL DEFAULT 'CONNECTED',
    capacity INTEGER NOT NULL,
    used_capacity INTEGER NOT NULL DEFAULT 0,
    object_count INTEGER NOT NULL DEFAULT 0,
    replica_count INTEGER NOT NULL DEFAULT 0,
    last_heartbeat TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS objects (
    object_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size INTEGER NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    checksum TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    replication_factor INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'HEALTHY',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replicas (
    replica_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL REFERENCES objects(object_id) ON DELETE CASCADE,
    node_id TEXT NOT NULL REFERENCES nodes(node_id),
    checksum TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    size INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'HEALTHY',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_replicas_object ON replicas(object_id);
CREATE INDEX IF NOT EXISTS idx_replicas_node ON replicas(node_id);

CREATE TABLE IF NOT EXISTS repair_jobs (
    repair_id TEXT PRIMARY KEY,
    object_id TEXT NOT NULL,
    replica_id TEXT NOT NULL,
    failed_node_id TEXT,
    replacement_node_id TEXT,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    progress INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    duration_ms INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_repairs_status ON repair_jobs(status);

CREATE TABLE IF NOT EXISTS rebalance_jobs (
    job_id TEXT PRIMARY KEY,
    replica_id TEXT NOT NULL,
    object_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    dest_node_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    progress INTEGER NOT NULL DEFAULT 0,
    bytes_moved INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    object_id TEXT,
    node_id TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_logs(created_at DESC);

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'INFO',
    message TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "replication_factor": str(settings.replication_factor),
    "health_check_interval": str(settings.health_check_interval),
    "repair_interval": str(settings.repair_interval),
    "integrity_check_interval": str(settings.integrity_check_interval),
    "rebalance_threshold": str(settings.rebalance_threshold),
    "max_storage_per_node": str(settings.max_storage_per_node),
}


def utcnow() -> str:
    """ISO-8601 UTC timestamp used across metadata records."""
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


class Database:
    """Thin SQLite wrapper with per-thread connections and serialized writes."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all_conns: list[sqlite3.Connection] = []
        self._conns_lock = threading.Lock()
        self._generation = 0
        db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        generation = self._generation
        cached = getattr(self._local, "cache", None)
        if cached is not None and cached[0] == generation:
            return cached[1]
        if cached is not None:
            try:
                cached[1].close()
            except sqlite3.Error:
                pass
        conn = self._connect()
        with self._conns_lock:
            self._all_conns.append(conn)
        self._local.cache = (generation, conn)
        return conn

    def rebind(self, new_path: Path) -> None:
        """Point this singleton at a new file (test isolation); closes old conns."""
        with self._write_lock:
            with self._conns_lock:
                for conn in self._all_conns:
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass
                self._all_conns.clear()
            self._generation += 1
            self.db_path = new_path
            new_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize(self) -> None:
        with self.write() as conn:
            conn.executescript(SCHEMA)
            for key, value in DEFAULT_SETTINGS.items():
                conn.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)", (key, value)
                )
        logger.info("Database initialized at %s", self.db_path)

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Serialized transaction: commit on success, rollback on error."""
        with self._write_lock:
            conn = self.conn
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def query_all(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def query_one(self, sql: str, params: tuple = ()) -> dict[str, Any] | None:
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def scalar(self, sql: str, params: tuple = ()) -> Any:
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    # -- settings ---------------------------------------------------------
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        return self.scalar("SELECT value FROM settings WHERE key=?", (key,)) or default

    def get_setting_int(self, key: str, default: int) -> int:
        raw = self.get_setting(key)
        try:
            return int(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    def set_setting(self, key: str, value: str) -> None:
        with self.write() as conn:
            conn.execute(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def all_settings(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self.query_all("SELECT * FROM settings")}


def get_setting(key: str, default: str | None = None) -> str | None:
    return db.get_setting(key, default)


def get_setting_int(key: str, default: int) -> int:
    return db.get_setting_int(key, default)


def set_setting(key: str, value: str) -> None:
    db.set_setting(key, value)


db = Database(settings.db_path)


def log_activity(
    conn: sqlite3.Connection,
    event_type: str,
    message: str,
    *,
    object_id: str | None = None,
    node_id: str | None = None,
) -> None:
    """Write an activity log row inside an open transaction."""
    conn.execute(
        "INSERT INTO activity_logs(event_type, message, object_id, node_id, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (event_type, message, object_id, node_id, utcnow()),
    )


def log_system_event(
    conn: sqlite3.Connection,
    event_type: str,
    message: str,
    *,
    severity: str = "INFO",
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO system_events(event_type, severity, message, payload, created_at) "
        "VALUES(?, ?, ?, ?, ?)",
        (event_type, severity, message, json.dumps(payload) if payload else None, utcnow()),
    )

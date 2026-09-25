"""Replica consistency: detect stale or divergent replicas across nodes."""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow

logger = logging.getLogger("vault.consistency")


def check_object_consistency(object_id: str) -> dict:
    """Compare replica versions/checksums against the authoritative metadata."""
    obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
    if obj is None:
        return {"object_id": object_id, "consistent": False, "reason": "object not found"}
    replicas = db.query_all(
        "SELECT * FROM replicas WHERE object_id=?", (object_id,)
    )
    stale, divergent = [], []
    for replica in replicas:
        if replica["version"] != obj["version"]:
            stale.append(replica["replica_id"])
        elif replica["checksum"] != obj["checksum"]:
            divergent.append(replica["replica_id"])
    consistent = not stale and not divergent
    return {
        "object_id": object_id,
        "authoritative_version": obj["version"],
        "authoritative_checksum": obj["checksum"],
        "consistent": consistent,
        "stale_replicas": stale,
        "divergent_replicas": divergent,
    }


def reconcile_stale_replicas(object_id: str) -> list[str]:
    """Reset stale replicas of an object only if their bytes verify on disk.

    A replica that reappears after a partition is marked STALE; reconciliation
    verifies the physical file against the authoritative checksum. If it
    matches, it becomes HEALTHY again; otherwise it stays STALE and repair
    replaces it. Metadata alone is never trusted over actual data.
    """
    replicas = db.query_all(
        "SELECT * FROM replicas WHERE object_id=? AND status='STALE'", (object_id,)
    )
    obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
    if obj is None:
        return []
    from backend.integrity.checksum import file_sha256

    reconciled: list[str] = []
    for replica in replicas:
        path = replica["node_id"] and _replica_file(replica["node_id"], object_id, obj["version"])
        actual = file_sha256(path) if path and path.is_file() else None
        if (
            replica["version"] == obj["version"]
            and actual == obj["checksum"]
        ):
            with db.write() as conn:
                conn.execute(
                    "UPDATE replicas SET status='HEALTHY', updated_at=? WHERE replica_id=?",
                    (utcnow(), replica["replica_id"]),
                )
                log_activity(
                    conn, "REPLICA_RECONCILED",
                    f"Stale replica {replica['node_id']} reconciled to HEALTHY ({object_id})",
                    object_id=object_id, node_id=replica["node_id"],
                )
            reconciled.append(replica["replica_id"])
    if reconciled:
        logger.info("Reconciled %d stale replica(s) for %s", len(reconciled), object_id)
    return reconciled


def _replica_file(node_id: str, object_id: str, version: int):
    from backend.config import settings
    from backend.storage.object_store import ObjectStore

    return ObjectStore(settings.storage_root).replica_path(node_id, object_id, version)

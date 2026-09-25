"""Metadata manager: consistent metadata updates and counter synchronization."""
from __future__ import annotations

import logging

from backend.database import db, utcnow
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.metadata_manager")


class MetadataManager:
    def __init__(self, store: ObjectStore) -> None:
        self.store = store

    def recount_all(self) -> dict:
        """Rebuild per-node counters from the replicas table (self-healing)."""
        rows = db.query_all(
            """
            SELECT node_id, COUNT(*) AS replica_count,
                   COUNT(DISTINCT object_id) AS object_count,
                   COALESCE(SUM(size),0) AS used_capacity
            FROM replicas WHERE status IN ('HEALTHY','STALE','REPAIRING')
            GROUP BY node_id
            """
        )
        by_node = {r["node_id"]: r for r in rows}
        nodes = [n["node_id"] for n in db.query_all("SELECT node_id FROM nodes")]
        with db.write() as conn:
            for node_id in nodes:
                stats = by_node.get(node_id)
                if stats:
                    conn.execute(
                        "UPDATE nodes SET replica_count=?, object_count=?, used_capacity=?, updated_at=? "
                        "WHERE node_id=?",
                        (stats["replica_count"], stats["object_count"], stats["used_capacity"],
                         utcnow(), node_id),
                    )
                else:
                    conn.execute(
                        "UPDATE nodes SET replica_count=0, object_count=0, used_capacity=0, updated_at=? "
                        "WHERE node_id=?",
                        (utcnow(), node_id),
                    )
        return {"nodes_updated": len(nodes)}

    def verify_disk_agrees_with_metadata(self) -> list[dict]:
        """Cross-check every healthy replica row against the physical file."""
        mismatches: list[dict] = []
        replicas = db.query_all(
            "SELECT r.*, (SELECT status FROM nodes n WHERE n.node_id=r.node_id) AS node_status "
            "FROM replicas r"
        )
        for replica in replicas:
            if replica["node_status"] not in ("ONLINE",):
                continue
            actual = self.store.compute_checksum(
                replica["node_id"], replica["object_id"], replica["version"]
            )
            obj = db.query_one(
                "SELECT checksum FROM objects WHERE object_id=?", (replica["object_id"],)
            )
            if actual is None or (obj and actual != obj["checksum"]):
                mismatches.append(
                    {"replica_id": replica["replica_id"], "node_id": replica["node_id"],
                     "object_id": replica["object_id"], "actual": actual}
                )
        return mismatches

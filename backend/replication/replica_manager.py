"""Replica manager: create replicas, verify checksums, repair and migrate.

All file I/O goes through ObjectStore; all bookkeeping goes through SQLite in
serialized write transactions. Replica writes are verified by checksum before
metadata is committed, so a failed write never poisons metadata.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from backend.database import db, log_activity, utcnow
from backend.exceptions import ObjectNotFoundError, ReplicaNotFoundError
from backend.integrity.checksum import file_sha256
from backend.storage.node_manager import NodeManager
from backend.storage.object_store import ObjectStore
from backend.storage.placement import PlacementPolicy

logger = logging.getLogger("vault.replica_manager")


class ReplicaManager:
    def __init__(self, store: ObjectStore, nodes: NodeManager, placement: PlacementPolicy) -> None:
        self.store = store
        self.nodes = nodes
        self.placement = placement

    # -- creation ---------------------------------------------------------
    def stage_replica_file(
        self, *, object_id: str, node_id: str, version: int,
        source_path: Path, expected_checksum: str,
    ) -> int:
        """Write and verify a replica on a node WITHOUT touching metadata.

        Used by the upload flow so object + replica rows can be committed
        atomically after every physical write has already verified.
        """
        written = self.store.write_object(node_id, object_id, version, source_path)
        actual = self.store.compute_checksum(node_id, object_id, version)
        if actual != expected_checksum:
            self.store.delete_object(node_id, object_id, version)
            raise IOError(
                f"Replica verification failed on {node_id}: expected {expected_checksum}, got {actual}"
            )
        return written

    def create_replicas_for_upload(
        self, *, object_id: str, source_path: Path, checksum: str, size: int,
        version: int, replication_factor: int, pinned_node: str | None = None,
    ) -> list[str]:
        """Place ``replication_factor`` verified replica files; returns node ids."""
        node_ids = self.placement.choose_nodes(
            replication_factor, object_id=object_id, pinned=pinned_node,
        )
        for node_id in node_ids:
            self.stage_replica_file(
                object_id=object_id, node_id=node_id, version=version,
                source_path=source_path, expected_checksum=checksum,
            )
        return node_ids

    def create_replica(
        self, *, object_id: str, source_node_id: str, dest_node_id: str, version: int
    ) -> dict:
        """Copy a replica from one node to another, verifying the checksum."""
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(f"Unknown object: {object_id}")
        src_path = self.store.replica_path(source_node_id, object_id, version)
        if not src_path.is_file():
            raise FileNotFoundError(f"Source replica missing on {source_node_id}")
        checksum = file_sha256(src_path)
        if checksum != obj["checksum"]:
            raise IOError(
                f"Source replica on {source_node_id} failed checksum; refusing to replicate corruption"
            )
        replica = self._write_replica(
            object_id=object_id, node_id=dest_node_id, source_path=src_path,
            checksum=checksum, size=obj["size"], version=version,
        )
        return replica

    def _write_replica(
        self, *, object_id: str, node_id: str, source_path: Path,
        checksum: str, size: int, version: int,
    ) -> dict:
        """Write the file to the node, verify, then commit metadata atomically."""
        written_size = self.store.write_object(node_id, object_id, version, source_path)
        actual_checksum = self.store.compute_checksum(node_id, object_id, version)
        if actual_checksum != checksum:
            self.store.delete_object(node_id, object_id, version)
            raise IOError(
                f"Replica verification failed on {node_id}: expected {checksum}, got {actual_checksum}"
            )
        now = utcnow()
        replica_id = f"rep_{object_id}_{node_id}"
        with db.write() as conn:
            conn.execute(
                "INSERT INTO replicas(replica_id, object_id, node_id, checksum, version, size, "
                "status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(replica_id) DO UPDATE SET checksum=excluded.checksum, "
                "version=excluded.version, size=excluded.size, status='HEALTHY', "
                "updated_at=excluded.updated_at",
                (replica_id, object_id, node_id, actual_checksum, version, written_size,
                 "HEALTHY", now, now),
            )
            conn.execute("UPDATE nodes SET last_heartbeat=? WHERE node_id=?", (now, node_id))
            log_activity(
                conn, "REPLICA_CREATED",
                f"Replica created -> {node_id} ({object_id})",
                object_id=object_id, node_id=node_id,
            )
        logger.info("Replica %s on %s verified and committed", replica_id, node_id)
        return db.query_one("SELECT * FROM replicas WHERE replica_id=?", (replica_id,))

    # -- reads ------------------------------------------------------------
    def list_replicas(self, object_id: str | None = None) -> list[dict]:
        if object_id:
            return db.query_all(
                "SELECT r.*, n.name AS node_name FROM replicas r "
                "JOIN nodes n ON n.node_id = r.node_id "
                "WHERE r.object_id=? ORDER BY r.node_id", (object_id,)
            )
        return db.query_all(
            "SELECT r.*, n.name AS node_name FROM replicas r "
            "JOIN nodes n ON n.node_id = r.node_id ORDER BY r.object_id, r.node_id"
        )

    def healthy_replicas(self, object_id: str) -> list[dict]:
        return db.query_all(
            "SELECT r.*, n.name AS node_name, n.status AS node_status "
            "FROM replicas r JOIN nodes n ON n.node_id = r.node_id "
            "WHERE r.object_id=? AND r.status='HEALTHY' AND n.status='ONLINE' "
            "AND n.network_status='CONNECTED' ORDER BY r.node_id",
            (object_id,),
        )

    def get_replica(self, replica_id: str) -> dict:
        replica = db.query_one("SELECT * FROM replicas WHERE replica_id=?", (replica_id,))
        if replica is None:
            raise ReplicaNotFoundError(f"Unknown replica: {replica_id}")
        return replica

    def choose_read_replica(self, object_id: str) -> dict:
        """Prefer healthy replicas on online nodes; round-robin across them."""
        healthy = self.healthy_replicas(object_id)
        if not healthy:
            raise ObjectNotFoundError(
                f"No healthy replica available for {object_id}"
            )
        idx = getattr(self, "_rr", 0) % len(healthy)
        self._rr = getattr(self, "_rr", 0) + 1
        return healthy[idx]

    # -- deletion / marking ------------------------------------------------
    def mark_replica_status(self, replica_id: str, status: str) -> None:
        with db.write() as conn:
            conn.execute(
                "UPDATE replicas SET status=?, updated_at=? WHERE replica_id=?",
                (status, utcnow(), replica_id),
            )

    def delete_replica(self, replica_id: str) -> dict:
        replica = self.get_replica(replica_id)
        self.store.delete_object(replica["node_id"], replica["object_id"], replica["version"])
        with db.write() as conn:
            conn.execute("DELETE FROM replicas WHERE replica_id=?", (replica_id,))
            log_activity(
                conn, "REPLICA_DELETED",
                f"Replica deleted from {replica['node_id']} ({replica['object_id']})",
                object_id=replica["object_id"], node_id=replica["node_id"],
            )
        return replica

    def delete_all_replicas(self, object_id: str) -> int:
        replicas = self.list_replicas(object_id)
        deleted = 0
        for replica in replicas:
            try:
                self.store.delete_object(
                    replica["node_id"], replica["object_id"], replica["version"]
                )
                with db.write() as conn:
                    conn.execute("DELETE FROM replicas WHERE replica_id=?", (replica["replica_id"],))
                deleted += 1
            except OSError as exc:
                logger.warning("Could not delete replica %s: %s", replica["replica_id"], exc)
        return deleted

    # -- repair -------------------------------------------------------------
    def repair_replica(self, replica_id: str) -> dict:
        """Rebuild a missing/corrupted replica from a healthy source."""
        replica = self.get_replica(replica_id)
        object_id = replica["object_id"]
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(f"Unknown object: {object_id}")

        sources = [
            r for r in self.healthy_replicas(object_id)
            if r["node_id"] != replica["node_id"]
        ]
        if not sources:
            raise ObjectNotFoundError(f"No healthy source replica for {object_id}")

        source = sources[0]
        src_path = self.store.replica_path(source["node_id"], object_id, source["version"])
        expected = obj["checksum"]

        with tempfile.TemporaryDirectory() as tmpdir:
            staged = Path(tmpdir) / "staged"
            shutil.copyfile(src_path, staged)
            staged_checksum = file_sha256(staged)
            if staged_checksum != expected:
                raise IOError(
                    f"Source replica on {source['node_id']} failed checksum; aborting repair"
                )
            written = self.store.write_object(
                replica["node_id"], object_id, replica["version"], staged
            )
        actual = self.store.compute_checksum(replica["node_id"], object_id, replica["version"])
        if actual != expected:
            self.store.delete_object(replica["node_id"], object_id, replica["version"])
            raise IOError(f"Repaired replica on {replica['node_id']} failed checksum")

        with db.write() as conn:
            conn.execute(
                "UPDATE replicas SET status='HEALTHY', checksum=?, size=?, version=?, updated_at=? "
                "WHERE replica_id=?",
                (expected, written, obj["version"], utcnow(), replica_id),
            )
            log_activity(
                conn, "REPLICA_REPAIRED",
                f"Replica repaired on {replica['node_id']} (source: {source['node_id']})",
                object_id=object_id, node_id=replica["node_id"],
            )
        return db.query_one("SELECT * FROM replicas WHERE replica_id=?", (replica_id,))

    # -- migration (rebalancing) --------------------------------------------
    def migrate_replica(self, replica_id: str, dest_node_id: str) -> dict:
        """Move a replica to another node; source is removed only after verify."""
        replica = self.get_replica(replica_id)
        object_id = replica["object_id"]
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(f"Unknown object: {object_id}")
        if dest_node_id == replica["node_id"]:
            raise ValueError("Destination equals source node")

        dest = self.nodes.get_node(dest_node_id)
        if dest["status"] != "ONLINE" or dest["network_status"] != "CONNECTED":
            raise ValueError(f"Destination {dest_node_id} is not ONLINE")

        src_path = self.store.replica_path(replica["node_id"], object_id, replica["version"])
        expected = obj["checksum"]
        written = self.store.write_object(dest_node_id, object_id, obj["version"], src_path)
        actual = self.store.compute_checksum(dest_node_id, object_id, obj["version"])
        if actual != expected:
            self.store.delete_object(dest_node_id, object_id, obj["version"])
            raise IOError(f"Migration verification failed on {dest_node_id}")

        now = utcnow()
        new_replica_id = f"rep_{object_id}_{dest_node_id}"
        with db.write() as conn:
            conn.execute(
                "INSERT INTO replicas(replica_id, object_id, node_id, checksum, version, size, "
                "status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (new_replica_id, object_id, dest_node_id, expected, obj["version"], written,
                 "HEALTHY", now, now),
            )
            conn.execute("DELETE FROM replicas WHERE replica_id=?", (replica_id,))
            self.store.delete_object(replica["node_id"], object_id, replica["version"])
            log_activity(
                conn, "REPLICA_MIGRATED",
                f"Replica migrated {replica['node_id']} -> {dest_node_id} ({object_id})",
                object_id=object_id, node_id=dest_node_id,
            )
        return db.query_one("SELECT * FROM replicas WHERE replica_id=?", (new_replica_id,))

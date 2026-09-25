"""Download service: serve bytes from the best replica with checksum failover."""
from __future__ import annotations

import logging
import os
import tempfile
import uuid
from pathlib import Path

from backend.database import db, log_activity, utcnow
from backend.exceptions import ObjectUnavailableError, ObjectNotFoundError
from backend.integrity.checksum import bytes_sha256
from backend.replication.replica_manager import ReplicaManager
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.download_service")


class DownloadService:
    def __init__(self, store: ObjectStore, replicas: ReplicaManager) -> None:
        self.store = store
        self.replicas = replicas

    def download(self, object_id: str) -> tuple[Path, dict]:
        """Return (staged_file_path, metadata) after checksum verification.

        A temporary copy is verified then handed to the API layer, which streams
        it back and cleans up. Corrupted replicas are skipped and repaired async.
        """
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(f"Unknown object: {object_id}")

        healthy = self.replicas.healthy_replicas(object_id)
        if not healthy:
            raise ObjectUnavailableError(
                f"Object {object_id} is unavailable: no healthy replicas"
            )

        # Rotate the starting replica so concurrent readers spread across nodes
        # (read balancing) and failover covers every replica, not just the first.
        start = self.replicas.choose_read_replica(object_id)
        start_idx = next(i for i, r in enumerate(healthy) if r["replica_id"] == start["replica_id"])
        ordered = healthy[start_idx:] + healthy[:start_idx]

        last_error: Exception | None = None
        for replica in ordered:
            node_id = replica["node_id"]
            try:
                payload = self.store.read_object(node_id, object_id, replica["version"])
                actual = bytes_sha256(payload)
                if actual != obj["checksum"]:
                    raise IOError(
                        f"CHECKSUM MISMATCH on {node_id}: expected {obj['checksum']}, got {actual}"
                    )
                # Unique staging file per download: concurrent readers of the
                # same object must never share (and corrupt) a temp path.
                fd, staged_name = tempfile.mkstemp(prefix=f"vault_dl_{object_id}_")
                staged = Path(staged_name)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload)
                with db.write() as conn:
                    log_activity(
                        conn, "OBJECT_DOWNLOADED",
                        f"Object downloaded: {obj['filename']} (from {node_id})",
                        object_id=object_id, node_id=node_id,
                    )
                return staged, {
                    "object_id": object_id,
                    "filename": obj["filename"],
                    "size": obj["size"],
                    "checksum": obj["checksum"],
                    "version": obj["version"],
                    "served_from_node": node_id,
                    "served_from_replica": replica["replica_id"],
                    "integrity": "VERIFIED",
                }
            except (OSError, IOError) as exc:
                last_error = exc
                logger.warning("Replica on %s failed for %s: %s", node_id, object_id, exc)
                self.replicas.mark_replica_status(replica["replica_id"], "CORRUPTED")
                from backend.repair.repair_manager import RepairManager

                RepairManager.instance().schedule_repair(
                    object_id=object_id, replica_id=replica["replica_id"],
                    failed_node_id=node_id, reason="CHECKSUM_MISMATCH",
                )
                continue

        raise ObjectUnavailableError(
            f"Object {object_id} unavailable: all replicas failed verification ({last_error})"
        )

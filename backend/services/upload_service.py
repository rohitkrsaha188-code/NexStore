"""Upload service: receive, hash, replicate, verify, commit metadata."""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from backend.database import db, log_activity, utcnow
from backend.exceptions import InvalidFilenameError, PayloadTooLargeError
from backend.config import settings
from backend.replication.replica_manager import ReplicaManager
from backend.storage.node_manager import NodeManager
from backend.storage.object_store import ObjectStore, file_sha256
from backend.storage.placement import PlacementPolicy

logger = logging.getLogger("vault.upload_service")

_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]")
MAX_FILENAME_LEN = 255


def sanitize_filename(name: str) -> str:
    """Strip path components and unsafe characters (path traversal defense)."""
    name = (name or "").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = _UNSAFE.sub("_", name).strip(". ")
    if not name:
        raise InvalidFilenameError("Filename is empty or invalid after sanitization")
    if len(name) > MAX_FILENAME_LEN:
        name = name[-MAX_FILENAME_LEN:]
    return name


class UploadService:
    def __init__(self, store: ObjectStore, nodes: NodeManager, placement: PlacementPolicy,
                 replicas: ReplicaManager) -> None:
        self.store = store
        self.nodes = nodes
        self.placement = placement
        self.replicas = replicas

    def upload(
        self, *, filename: str, tmp_path: Path, size: int, content_type: str,
        replication_factor: int | None = None, pinned_node: str | None = None,
    ) -> dict:
        from backend.database import get_setting_int

        rf = replication_factor or get_setting_int("replication_factor", settings.replication_factor)
        if rf < 1:
            raise ValidationError("replication_factor must be >= 1")

        filename = sanitize_filename(filename)
        if size > settings.max_upload_size:
            raise PayloadTooLargeError(
                f"File exceeds max upload size ({settings.max_upload_size} bytes)"
            )
        checksum = file_sha256(tmp_path)

        object_id = f"obj_{uuid4_hex()[:20]}"
        version = 1
        # 1) Place and verify physical replicas first (no metadata yet).
        node_ids = self.replicas.create_replicas_for_upload(
            object_id=object_id, source_path=tmp_path, checksum=checksum, size=size,
            version=version, replication_factor=rf, pinned_node=pinned_node,
        )
        # 2) Commit object + replica metadata atomically.
        now = utcnow()
        replica_rows: list[dict] = []
        with db.write() as conn:
            conn.execute(
                "INSERT INTO objects(object_id, filename, size, content_type, checksum, version, "
                "replication_factor, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (object_id, filename, size, content_type or "application/octet-stream",
                 checksum, version, rf, "HEALTHY", now, now),
            )
            for node_id in node_ids:
                replica_id = f"rep_{object_id}_{node_id}"
                conn.execute(
                    "INSERT INTO replicas(replica_id, object_id, node_id, checksum, version, "
                    "size, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (replica_id, object_id, node_id, checksum, version, size, "HEALTHY",
                     now, now),
                )
                replica_rows.append({
                    "replica_id": replica_id, "object_id": object_id, "node_id": node_id,
                    "checksum": checksum, "version": version, "size": size,
                    "status": "HEALTHY", "created_at": now, "updated_at": now,
                })
            log_activity(
                conn, "OBJECT_UPLOADED",
                f"Object uploaded: {filename} ({size} bytes, RF={rf})",
                object_id=object_id,
            )
            for node_id in node_ids:
                log_activity(
                    conn, "REPLICA_CREATED",
                    f"Replica created -> {node_id} ({filename})",
                    object_id=object_id, node_id=node_id,
                )
        logger.info("Uploaded %s as %s with %d replica(s)", filename, object_id, len(node_ids))
        return {
            "object_id": object_id,
            "filename": filename,
            "size": size,
            "checksum": checksum,
            "version": version,
            "replication_factor": rf,
            "status": "HEALTHY",
            "replicas": replica_rows,
            "placement": {"nodes": node_ids, "strategy": "least-utilized-greedy"},
        }


def uuid4_hex() -> str:
    import uuid

    return uuid.uuid4().hex

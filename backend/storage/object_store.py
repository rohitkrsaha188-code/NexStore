"""Physical object storage on individual simulated storage nodes.

Each node owns an isolated directory: storage_nodes/nodeX/data/. Files are
written to temporary paths and atomically renamed into place. Nothing here
talks to SQLite; the node manager and metadata layer own bookkeeping.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("vault.object_store")

CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming chunks


class ObjectStore:
    """Filesystem-backed object store for all simulated nodes."""

    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root

    def node_data_dir(self, node_id: str) -> Path:
        return self.storage_root / node_id / "data"

    def replica_path(self, node_id: str, object_id: str, version: int) -> Path:
        safe_object_id = _sanitize_component(object_id)
        return self.node_data_dir(node_id) / f"{safe_object_id}.v{version}"

    def ensure_node_dirs(self, node_ids: list[str]) -> None:
        for node_id in node_ids:
            self.node_data_dir(node_id).mkdir(parents=True, exist_ok=True)

    def write_object(self, node_id: str, object_id: str, version: int, source_path: Path) -> int:
        """Stream ``source_path`` into the node and return the byte count."""
        dest = self.replica_path(node_id, object_id, version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        size = 0
        with open(source_path, "rb") as src, open(tmp, "wb") as out:
            while chunk := src.read(CHUNK_SIZE):
                out.write(chunk)
                size += len(chunk)
        _atomic_replace(tmp, dest)
        logger.debug("wrote %s on %s (%d bytes)", object_id, node_id, size)
        return size

    def write_bytes(self, node_id: str, object_id: str, version: int, payload: bytes) -> int:
        dest = self.replica_path(node_id, object_id, version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(payload)
        _atomic_replace(tmp, dest)
        return len(payload)

    def read_object(self, node_id: str, object_id: str, version: int) -> bytes:
        path = self.replica_path(node_id, object_id, version)
        if not path.is_file():
            raise FileNotFoundError(f"replica missing on {node_id}: {path}")
        return path.read_bytes()

    def read_stream(self, node_id: str, object_id: str, version: int):
        """Return an open binary handle for streaming downloads."""
        path = self.replica_path(node_id, object_id, version)
        if not path.is_file():
            raise FileNotFoundError(f"replica missing on {node_id}: {path}")
        return open(path, "rb")

    def compute_checksum(self, node_id: str, object_id: str, version: int) -> str | None:
        path = self.replica_path(node_id, object_id, version)
        return file_sha256(path) if path.is_file() else None

    def size_on_disk(self, node_id: str, object_id: str, version: int) -> int:
        path = self.replica_path(node_id, object_id, version)
        return path.stat().st_size if path.is_file() else 0

    def delete_object(self, node_id: str, object_id: str, version: int) -> bool:
        path = self.replica_path(node_id, object_id, version)
        if path.is_file():
            path.unlink()
            logger.debug("deleted %s on %s", object_id, node_id)
            return True
        return False

    def node_used_bytes(self, node_id: str) -> int:
        total = 0
        data_dir = self.node_data_dir(node_id)
        if data_dir.is_dir():
            for item in data_dir.iterdir():
                if item.is_file():
                    total += item.stat().st_size
        return total

    def corrupt_replica(self, node_id: str, object_id: int | str, version: int) -> bool:
        """Flip bytes in a stored replica so its checksum no longer matches."""
        path = self.replica_path(node_id, str(object_id), version)
        if not path.is_file() or path.stat().st_size == 0:
            return False
        data = bytearray(path.read_bytes())
        payload = b"VAULT_CORRUPTION" * max(1, min(len(data) // 16, 64))
        end = min(len(data), len(payload))
        data[:end] = payload[:end]
        path.write_bytes(bytes(data))
        logger.warning("corrupted replica %s v%d on %s", object_id, version, node_id)
        return True


def file_sha256(path: Path) -> str:
    """SHA-256 of a file, computed with streaming chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _atomic_replace(tmp: Path, dest: Path) -> None:
    tmp.replace(dest)


def _sanitize_component(value: str) -> str:
    """Strip anything that could escape the node data directory."""
    return "".join(ch for ch in value if ch.isalnum() or ch in "-_") or "obj"

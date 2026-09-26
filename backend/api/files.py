"""File/object endpoints: upload, list, download, delete, verify, corrupt."""
from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import FileResponse

from backend.api.deps import get_delete_service, get_download_service, get_store, get_upload_service
from backend.config import settings
from backend.database import db
from backend.exceptions import ObjectNotFoundError, ValidationError
from backend.integrity.verifier import IntegrityVerifier
from backend.schemas import (
    CorruptResponse, FileDetail, ObjectOut, UploadResponse, VerifyResponse,
)
from backend.services.object_service import get_object_detail, list_objects

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("", response_model=list[ObjectOut])
def get_files() -> list[dict]:
    return list_objects()


@router.get("/{object_id}", response_model=FileDetail)
def get_file(object_id: str) -> dict:
    return get_object_detail(object_id)


@router.post("/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    replication_factor: int | None = Query(default=None, ge=1, le=5),
) -> dict:
    filename = (file.filename or "upload.bin").strip()
    content_type = file.content_type or "application/octet-stream"

    # Stream to a temp file so memory stays flat for large uploads.
    tmp = tempfile.NamedTemporaryFile(prefix="vault_up_", suffix=".bin", delete=False)
    size = 0
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_size:
                raise ValidationError(f"File too large (max {settings.max_upload_size} bytes)")
            tmp.write(chunk)
        tmp.close()
        if size == 0:
            raise ValidationError("Uploaded file is empty")
        return get_upload_service().upload(
            filename=filename, tmp_path=tmp.name, size=size, content_type=content_type,
            replication_factor=replication_factor,
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.post("/upload-to-node", response_model=UploadResponse)
async def upload_file_to_node(
    file: UploadFile = File(...),
    node_id: str = Query(...),
    replication_factor: int | None = Query(default=None, ge=1, le=5),
) -> dict:
    """Add File To Node: pin the first replica to ``node_id``; the rest follow
    the normal least-utilized, never-co-located placement policy."""
    filename = (file.filename or "upload.bin").strip()
    content_type = file.content_type or "application/octet-stream"

    tmp = tempfile.NamedTemporaryFile(prefix="vault_up_", suffix=".bin", delete=False)
    size = 0
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_size:
                raise ValidationError(f"File too large (max {settings.max_upload_size} bytes)")
            tmp.write(chunk)
        tmp.close()
        if size == 0:
            raise ValidationError("Uploaded file is empty")
        return get_upload_service().upload(
            filename=filename, tmp_path=tmp.name, size=size, content_type=content_type,
            replication_factor=replication_factor, pinned_node=node_id,
        )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.get("/{object_id}/download")
def download_file(object_id: str):
    staged_path, meta = get_download_service().download(object_id)
    headers = {"X-Served-From-Node": meta["served_from_node"],
               "X-Integrity": meta["integrity"]}
    try:
        return FileResponse(
            path=staged_path, filename=meta["filename"], media_type="application/octet-stream",
            headers=headers,
        )
    finally:
        _schedule_cleanup(staged_path)


def _schedule_cleanup(path: str) -> None:
    """Remove the staged temp file after the response is sent (best effort)."""
    import threading

    def _cleanup() -> None:
        import time

        time.sleep(5)
        try:
            os.unlink(path)
        except OSError:
            pass

    threading.Thread(target=_cleanup, daemon=True).start()


@router.delete("/{object_id}")
def delete_file(object_id: str) -> dict:
    return get_delete_service().delete(object_id)


@router.get("/{object_id}/replicas")
def get_file_replicas(object_id: str) -> dict:
    detail = get_object_detail(object_id)
    return {"object_id": object_id, "replicas": detail["replicas"],
            "required": detail["required_replicas"]}


@router.post("/{object_id}/verify", response_model=VerifyResponse)
def verify_file(object_id: str) -> dict:
    verifier = IntegrityVerifier(store=get_store())
    return verifier.verify_object(object_id)


@router.post("/{object_id}/corrupt", response_model=CorruptResponse)
def corrupt_object_replica(object_id: str, node_id: str | None = Query(default=None)) -> dict:
    """Simulate silent data corruption on one replica of the object."""
    detail = get_object_detail(object_id)
    candidates = [
        r for r in detail["replicas"]
        if r["status"] in ("HEALTHY", "STALE") and _node_online(r["node_id"])
    ]
    if node_id:
        candidates = [r for r in candidates if r["node_id"] == node_id]
    if not candidates:
        raise ValidationError("No corruptible replica available (need an ONLINE node with a HEALTHY replica)")
    target = candidates[0]

    from backend.integrity.corruption import corrupt_replica

    result = corrupt_replica(get_store(), target["replica_id"])
    detected = IntegrityVerifier(store=get_store()).verify_object(object_id)
    return CorruptResponse(
        replica_id=result["replica_id"], node_id=result["node_id"],
        object_id=object_id, detected=detected["corrupted"] > 0,
    )


def _node_online(node_id: str) -> bool:
    row = db.query_one("SELECT status, network_status FROM nodes WHERE node_id=?", (node_id,))
    return bool(row and row["status"] == "ONLINE" and row["network_status"] == "CONNECTED")

"""Integrity endpoints: cluster scans and single-replica verification."""
from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import get_replica_manager, get_store
from backend.exceptions import ReplicaNotFoundError
from backend.integrity.verifier import IntegrityVerifier
from backend.schemas import VerifyResponse

router = APIRouter(prefix="/api/integrity", tags=["integrity"])


@router.post("/scan")
def integrity_scan() -> dict:
    verifier = IntegrityVerifier(store=get_store())
    return verifier.scan_cluster()


@router.get("/report")
def integrity_report() -> dict:
    verifier = IntegrityVerifier(store=get_store())
    replicas = get_replica_manager().list_replicas()
    results = []
    for replica in replicas:
        if replica["status"] in ("HEALTHY", "CORRUPTED", "STALE"):
            try:
                results.append(verifier.verify_replica(replica))
            except Exception:  # noqa: BLE001
                continue
    return {"replicas": results}


@router.post("/replica/{replica_id}/verify")
def verify_replica(replica_id: str) -> dict:
    try:
        replica = get_replica_manager().get_replica(replica_id)
    except ReplicaNotFoundError:
        raise
    verifier = IntegrityVerifier(store=get_store())
    return verifier.verify_replica(replica)

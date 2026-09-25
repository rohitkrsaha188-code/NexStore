"""Replica endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from backend.api.deps import get_replica_manager
from backend.database import db
from backend.replication.consistency import check_object_consistency
from backend.schemas import ReplicaOut

router = APIRouter(prefix="/api/replicas", tags=["replicas"])


@router.get("", response_model=list[ReplicaOut])
def list_replicas(object_id: str | None = Query(default=None)) -> list[dict]:
    rows = get_replica_manager().list_replicas(object_id)
    return [dict(row) for row in rows]


@router.get("/{replica_id}", response_model=ReplicaOut)
def get_replica(replica_id: str) -> dict:
    replica = get_replica_manager().get_replica(replica_id)
    node = db.query_one("SELECT name FROM nodes WHERE node_id=?", (replica["node_id"],))
    return {**replica, "node_name": node["name"] if node else ""}


@router.get("/consistency/{object_id}")
def consistency(object_id: str) -> dict:
    return check_object_consistency(object_id)

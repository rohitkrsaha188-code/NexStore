"""Node endpoints: listing, detail, failure/restore/partition/reconnect."""
from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import get_node_manager
from backend.database import get_setting_int
from backend.health.health_checker import run_health_check
from backend.schemas import NodeActionResponse, NodeOut

router = APIRouter(prefix="/api/nodes", tags=["nodes"])


def _to_out(node: dict) -> dict:
    utilization = round(100 * node["used_capacity"] / node["capacity"], 2) if node["capacity"] else 0.0
    return {**node, "utilization": utilization}


@router.get("", response_model=list[NodeOut])
def list_nodes() -> list[dict]:
    return [_to_out(node) for node in get_node_manager().list_nodes()]


@router.get("/{node_id}", response_model=NodeOut)
def get_node(node_id: str) -> dict:
    return _to_out(get_node_manager().get_node(node_id))


@router.get("/{node_id}/replicas")
def node_replicas(node_id: str) -> dict:
    get_node_manager().get_node(node_id)
    from backend.database import db

    rows = db.query_all(
        "SELECT r.*, o.filename FROM replicas r JOIN objects o ON o.object_id=r.object_id "
        "WHERE r.node_id=? ORDER BY r.object_id",
        (node_id,),
    )
    return {"node_id": node_id, "replicas": rows}


@router.get("/{node_id}/objects")
def node_objects(node_id: str) -> dict:
    """Stored objects on one node for the Node Details panel."""
    node = get_node_manager().get_node(node_id)
    from backend.database import db

    rows = db.query_all(
        "SELECT r.replica_id, r.object_id, o.filename, r.size, r.checksum, r.version, "
        "r.status AS replica_status, o.status AS object_status, r.created_at "
        "FROM replicas r JOIN objects o ON o.object_id=r.object_id "
        "WHERE r.node_id=? ORDER BY r.created_at DESC",
        (node_id,),
    )
    utilization = round(100 * node["used_capacity"] / node["capacity"], 2) if node["capacity"] else 0.0
    return {
        "node": {**node, "utilization": utilization},
        "available": max(node["capacity"] - node["used_capacity"], 0),
        "objects": rows,
    }


@router.post("/{node_id}/fail", response_model=NodeActionResponse)
def fail_node(node_id: str) -> NodeActionResponse:
    node = get_node_manager().fail_node(node_id)
    # Immediately surface lost replicas as repair work.
    from backend.health.failure_detector import detect_degraded_objects

    detect_degraded_objects()
    return NodeActionResponse(
        node_id=node_id, status=node["status"], network_status=node["network_status"],
        message=f"Node {node_id} failed; degraded objects scheduled for repair",
    )


@router.post("/{node_id}/restore", response_model=NodeActionResponse)
def restore_node(node_id: str) -> NodeActionResponse:
    node = get_node_manager().restore_node(node_id)
    from backend.replication.consistency import reconcile_stale_replicas

    reconciled = 0
    for row in _object_ids_for_node(node_id):
        reconciled += len(reconcile_stale_replicas(row))
    return NodeActionResponse(
        node_id=node_id, status=node["status"], network_status=node["network_status"],
        message=f"Node {node_id} restored; {reconciled} stale replica(s) queued for verification",
    )


@router.post("/{node_id}/partition", response_model=NodeActionResponse)
def partition_node(node_id: str) -> NodeActionResponse:
    node = get_node_manager().partition_node(node_id)
    from backend.health.failure_detector import detect_degraded_objects

    detect_degraded_objects()
    return NodeActionResponse(
        node_id=node_id, status=node["status"], network_status=node["network_status"],
        message=f"Node {node_id} partitioned; replicas marked unreachable, metadata retained",
    )


@router.post("/{node_id}/reconnect", response_model=NodeActionResponse)
def reconnect_node(node_id: str) -> NodeActionResponse:
    node = get_node_manager().restore_node(node_id)
    from backend.replication.consistency import reconcile_stale_replicas

    for object_id in _object_ids_for_node(node_id):
        reconcile_stale_replicas(object_id)
    run_health_check(heartbeat_timeout=get_setting_int("health_check_interval", 5) * 3)
    return NodeActionResponse(
        node_id=node_id, status=node["status"], network_status=node["network_status"],
        message=f"Node {node_id} reconnected; state reconciled",
    )


def _object_ids_for_node(node_id: str) -> list[str]:
    from backend.database import db

    return [
        row["object_id"]
        for row in db.query_all("SELECT DISTINCT object_id FROM replicas WHERE node_id=?", (node_id,))
    ]

"""Node lifecycle management and per-node counters."""
from __future__ import annotations

import logging

from backend.database import db, log_activity, log_system_event, utcnow
from backend.exceptions import NodeNotFoundError
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.node_manager")

NODE_NAMES = {
    "node1": "NODE 01",
    "node2": "NODE 02",
    "node3": "NODE 03",
    "node4": "NODE 04",
    "node5": "NODE 05",
}


class NodeManager:
    def __init__(self, store: ObjectStore) -> None:
        self.store = store
        self._last_heartbeat_ms: dict[str, int] = {}

    def initialize_nodes(self) -> list[dict]:
        """Create the simulated node fleet on first startup (idempotent)."""
        node_ids = [f"node{i}" for i in range(1, settings_node_count() + 1)]
        self.store.ensure_node_dirs(node_ids)
        now = utcnow()
        with db.write() as conn:
            for i, node_id in enumerate(node_ids, start=1):
                existing = conn.execute(
                    "SELECT node_id FROM nodes WHERE node_id=?", (node_id,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE nodes SET status='ONLINE', network_status='CONNECTED', "
                        "health_status='HEALTHY', last_heartbeat=?, capacity=? WHERE node_id=?",
                        (now, _capacity_for(i), node_id),
                    )
                    continue
                conn.execute(
                    "INSERT INTO nodes(node_id, name, status, health_status, network_status, "
                    "capacity, used_capacity, object_count, replica_count, last_heartbeat, "
                    "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        node_id,
                        NODE_NAMES.get(node_id, node_id.upper()),
                        "ONLINE",
                        "HEALTHY",
                        "CONNECTED",
                        _capacity_for(i),
                        0,
                        0,
                        0,
                        now,
                        now,
                        now,
                    ),
                )
                log_activity(conn, "NODE_REGISTERED", f"Node registered: {node_id}", node_id=node_id)
        logger.info("Initialized %d storage nodes", len(node_ids))
        return db.query_all("SELECT * FROM nodes ORDER BY node_id")

    def list_nodes(self) -> list[dict]:
        return db.query_all("SELECT * FROM nodes ORDER BY node_id")

    def get_node(self, node_id: str) -> dict:
        node = db.query_one("SELECT * FROM nodes WHERE node_id=?", (node_id,))
        if node is None:
            raise NodeNotFoundError(f"Unknown node: {node_id}")
        return node

    def require_online(self, node_id: str) -> dict:
        node = self.get_node(node_id)
        if node["status"] != "ONLINE":
            raise NodeNotFoundError(f"Node {node_id} is {node['status']}, not ONLINE")
        return node

    def healthy_nodes(self) -> list[dict]:
        return db.query_all(
            "SELECT * FROM nodes WHERE status='ONLINE' AND network_status='CONNECTED' "
            "ORDER BY used_capacity ASC"
        )

    def online_node_ids(self) -> list[str]:
        return [row["node_id"] for row in self.healthy_nodes()]

    def set_status(
        self, node_id: str, status: str, network_status: str | None = None
    ) -> dict:
        self.get_node(node_id)
        with db.write() as conn:
            sets = ["status=?", "last_heartbeat=?", "updated_at=?"]
            params: list = [status, utcnow(), utcnow()]
            if network_status is not None:
                sets.append("network_status=?")
                params.append(network_status)
            params.append(node_id)
            conn.execute(f"UPDATE nodes SET {', '.join(sets)} WHERE node_id=?", params)
        logger.info("Node %s status -> %s", node_id, status)
        return self.get_node(node_id)

    def touch_heartbeat(self, node_id: str) -> None:
        with db.write() as conn:
            conn.execute(
                "UPDATE nodes SET last_heartbeat=?, updated_at=? WHERE node_id=?",
                (utcnow(), utcnow(), node_id),
            )

    def fail_node(self, node_id: str) -> dict:
        node = self.set_status(node_id, "FAILED", "DISCONNECTED")
        with db.write() as conn:
            conn.execute(
                "UPDATE replicas SET status='UNAVAILABLE', updated_at=? WHERE node_id=? AND status='HEALTHY'",
                (utcnow(), node_id),
            )
            log_activity(conn, "NODE_FAILED", f"Node {node_id} marked FAILED (simulated crash)", node_id=node_id)
            log_system_event(conn, "NODE_FAILED", f"Node {node_id} failed", severity="ERROR", payload={"node_id": node_id})
        self._recount_nodes(node_ids=[node_id])
        return node

    def partition_node(self, node_id: str) -> dict:
        """Network partition: node keeps data but is temporarily unreachable."""
        node = self.set_status(node_id, "PARTITIONED", "PARTITIONED")
        with db.write() as conn:
            conn.execute(
                "UPDATE replicas SET status='UNAVAILABLE', updated_at=? WHERE node_id=? AND status='HEALTHY'",
                (utcnow(), node_id),
            )
            log_activity(conn, "NETWORK_PARTITION", f"Network partition: {node_id} unreachable", node_id=node_id)
            log_system_event(conn, "NETWORK_PARTITION", f"Node {node_id} partitioned", severity="WARNING", payload={"node_id": node_id})
        self._recount_nodes(node_ids=[node_id])
        return node

    def restore_node(self, node_id: str) -> dict:
        node = self.get_node(node_id)
        with db.write() as conn:
            conn.execute(
                "UPDATE nodes SET status='ONLINE', network_status='CONNECTED', health_status='HEALTHY', "
                "last_heartbeat=?, updated_at=? WHERE node_id=?",
                (utcnow(), utcnow(), node_id),
            )
            # Replicas on a recovered node become candidates; reconciliation verifies them.
            conn.execute(
                "UPDATE replicas SET status='STALE', updated_at=? WHERE node_id=? AND status='UNAVAILABLE'",
                (utcnow(), node_id),
            )
            log_activity(conn, "NODE_RECOVERED", f"Node {node_id} restored to ONLINE", node_id=node_id)
            log_system_event(conn, "NODE_RECOVERED", f"Node {node_id} recovered", payload={"node_id": node_id})
        self._recount_nodes(node_ids=[node_id])
        return self.get_node(node_id)

    def reconnect_node(self, node_id: str) -> dict:
        return self.restore_node(node_id)

    def _recount_nodes(self, node_ids: list[str] | None = None) -> None:
        """Sync per-node replica_count/object_count/used_capacity from disk+DB."""
        rows = db.query_all(
            """
            SELECT r.node_id,
                   COUNT(*) AS replica_count,
                   COUNT(DISTINCT r.object_id) AS object_count,
                   COALESCE(SUM(r.size), 0) AS used_capacity
            FROM replicas r
            WHERE r.status IN ('HEALTHY','STALE','REPAIRING')
            GROUP BY r.node_id
            """
        )
        by_node = {row["node_id"]: row for row in rows}
        targets = node_ids or [row["node_id"] for row in self.list_nodes()]
        with db.write() as conn:
            for node_id in targets:
                stats = by_node.get(node_id)
                if stats:
                    conn.execute(
                        "UPDATE nodes SET replica_count=?, object_count=?, used_capacity=?, updated_at=? "
                        "WHERE node_id=?",
                        (stats["replica_count"], stats["object_count"], stats["used_capacity"], utcnow(), node_id),
                    )
                else:
                    conn.execute(
                        "UPDATE nodes SET replica_count=0, object_count=0, used_capacity=0, updated_at=? "
                        "WHERE node_id=?",
                        (utcnow(), node_id),
                    )


def settings_node_count() -> int:
    from backend.config import settings

    return settings.node_count


# Slight per-node variance keeps rebalancing scenarios realistic.
_CAPACITY_FACTORS = {1: 1.0, 2: 1.0, 3: 0.9, 4: 1.0, 5: 0.8}


def _capacity_for(index: int) -> int:
    """Real usable free disk space, distributed across the simulated nodes.

    All nodes share one physical volume, so the fleet total equals the actual
    free space on disk (previously a fixed 10 GB demo value per node).
    """
    import shutil

    from backend.config import settings

    settings.ensure_dirs()
    try:
        free = shutil.disk_usage(settings.storage_root).free
    except OSError:
        free = int(settings.max_storage_per_node)
    weight = _CAPACITY_FACTORS.get(index, 1.0) / sum(_CAPACITY_FACTORS.values())
    return int(free * weight)

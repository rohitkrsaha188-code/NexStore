"""Replica placement policy considering health, capacity, and spread.

Greedy least-utilized placement with strict node-uniqueness per object so
replicas of one object never share a node.
"""
from __future__ import annotations

import logging

from backend.database import db
from backend.exceptions import InsufficientNodesError
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.placement")


class PlacementPolicy:
    """Chooses target nodes for replicas of an object."""

    def __init__(self, store: ObjectStore) -> None:
        self.store = store

    def choose_nodes(self, count: int, *, exclude: set[str] | None = None,
                     object_id: str | None = None,
                     pinned: str | None = None) -> list[str]:
        """Pick ``count`` distinct healthy nodes, least-utilized first.

        ``exclude`` removes nodes (e.g. ones already holding a replica or a
        failed node that should not receive fresh data). ``pinned`` forces a
        specific node first (Add File To Node); remaining replicas still honor
        the no-co-location rule via ``exclude``.
        """
        exclude = set(exclude or set())
        chosen: list[str] = []
        if pinned:
            node = db.query_one(
                "SELECT node_id FROM nodes WHERE node_id=? AND status='ONLINE' "
                "AND network_status='CONNECTED' AND health_status='HEALTHY'",
                (pinned,),
            )
            if not node:
                from backend.exceptions import NodeNotFoundError

                raise NodeNotFoundError(
                    f"Pinned target {pinned} is not an ONLINE, healthy node"
                )
            if node["node_id"] in exclude:
                raise ValueError(f"Pinned target {pinned} conflicts with excluded set")
            chosen.append(node["node_id"])
            exclude.add(node["node_id"])
            count -= 1
            if count <= 0:
                logger.info("Placement for %s -> %s (pinned)", object_id or "new-object", chosen)
                return chosen
        candidates = db.query_all(
            "SELECT node_id, capacity, used_capacity FROM nodes "
            "WHERE status='ONLINE' AND network_status='CONNECTED' "
            "AND health_status='HEALTHY' ORDER BY used_capacity ASC, node_id ASC"
        )
        candidates = [c for c in candidates if c["node_id"] not in exclude]
        if len(candidates) < count:
            raise InsufficientNodesError(
                f"Need {count} healthy node(s) but only {len(candidates)} available "
                f"(excluded: {sorted(exclude) or 'none'})"
            )
        chosen.extend(c["node_id"] for c in candidates[:count])
        logger.info("Placement for %s -> %s", object_id or "new-object", chosen)
        return chosen

    def choose_replacement_node(self, *, exclude: set[str]) -> str:
        nodes = self.choose_nodes(1, exclude=exclude)
        return nodes[0]

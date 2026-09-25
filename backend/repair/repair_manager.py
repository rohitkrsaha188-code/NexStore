"""Repair manager: schedules and executes replica repairs.

A singleton so API routes and background workers share one coordinator.
"""
from __future__ import annotations

import logging
import threading
import time

from backend.config import settings
from backend.database import db, log_activity, utcnow
from backend.exceptions import ObjectNotFoundError
from backend.replication.replica_manager import ReplicaManager
from backend.repair.repair_queue import claim_next_job, enqueue_repair, finish_job
from backend.storage.node_manager import NodeManager
from backend.storage.object_store import ObjectStore
from backend.storage.placement import PlacementPolicy

logger = logging.getLogger("vault.repair_manager")


class RepairManager:
    _instance: "RepairManager | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, store: ObjectStore, nodes: NodeManager, placement: PlacementPolicy,
                 replicas: ReplicaManager) -> None:
        self.store = store
        self.nodes = nodes
        self.placement = placement
        self.replicas = replicas
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> "RepairManager":
        with cls._instance_lock:
            if cls._instance is None:
                store = ObjectStore(settings.storage_root)
                nodes = NodeManager(store)
                placement = PlacementPolicy(store)
                replicas = ReplicaManager(store, nodes, placement)
                cls._instance = cls(store, nodes, placement, replicas)
            return cls._instance

    # -- scheduling ---------------------------------------------------------
    def schedule_repair(
        self, *, object_id: str, replica_id: str, failed_node_id: str | None, reason: str
    ) -> str | None:
        return enqueue_repair(
            object_id=object_id, replica_id=replica_id, reason=reason, failed_node_id=failed_node_id
        )

    def schedule_missing_replicas(self, *, object_id: str, desired: int) -> list[str]:
        """Ensure the object has ``desired`` placements; queue repair for what's missing."""
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(object_id)
        replicas = db.query_all("SELECT * FROM replicas WHERE object_id=?", (object_id,))
        queued: list[str] = []

        # Missing replica rows: fewer rows than desired (node died pre-write).
        if len(replicas) < desired:
            existing_nodes = {r["node_id"] for r in replicas}
            needed = desired - len(replicas)
            node_ids = self.placement.choose_nodes(
                needed, exclude=existing_nodes, object_id=object_id
            )
            for node_id in node_ids:
                replica_id = f"rep_{object_id}_{node_id}"
                with db.write() as conn:
                    conn.execute(
                        "INSERT INTO replicas(replica_id, object_id, node_id, checksum, version, "
                        "size, status, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (replica_id, object_id, node_id, obj["checksum"], obj["version"], 0,
                         "MISSING", utcnow(), utcnow()),
                    )
                repair_id = enqueue_repair(
                    object_id=object_id, replica_id=replica_id, reason="MISSING_REPLICA",
                    failed_node_id=None,
                )
                if repair_id:
                    queued.append(replica_id)

        # Existing rows that are corrupted/unavailable: rebuild in place if the
        # node returns, or replace via the worker if it stays down.
        for replica in replicas:
            if replica["status"] in ("CORRUPTED", "UNAVAILABLE"):
                repair_id = enqueue_repair(
                    object_id=object_id, replica_id=replica["replica_id"],
                    reason="REBUILD_REPLICA", failed_node_id=replica["node_id"],
                )
                if repair_id:
                    queued.append(replica["replica_id"])
        return queued

    # -- execution -----------------------------------------------------------
    def run_pending_repairs(self, max_jobs: int = 10) -> int:
        """Drain the queue; used by the repair worker and tests."""
        executed = 0
        while executed < max_jobs:
            job = claim_next_job()
            if job is None:
                break
            executed += 1
            start = time.perf_counter()
            try:
                self._execute_job(job)
                duration_ms = int((time.perf_counter() - start) * 1000)
                finish_job(job["repair_id"], status="COMPLETED", progress=100,
                           duration_ms=duration_ms)
            except Exception as exc:  # noqa: BLE001 - a failed job must not kill the worker
                duration_ms = int((time.perf_counter() - start) * 1000)
                logger.exception("Repair job %s failed: %s", job["repair_id"], exc)
                finish_job(job["repair_id"], status="FAILED", progress=100, error=str(exc),
                           duration_ms=duration_ms)
        return executed

    def _execute_job(self, job: dict) -> None:
        replica_id = job["replica_id"]
        object_id = job["object_id"]
        replica = db.query_one("SELECT * FROM replicas WHERE replica_id=?", (replica_id,))
        if replica is None:
            logger.info("Repair %s: replica row vanished (already replaced); skipping",
                        job["repair_id"])
            return
        if replica["status"] == "HEALTHY":
            logger.info("Repair %s: replica already healthy; skipping", job["repair_id"])
            return

        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(object_id)

        node = self.nodes.get_node(replica["node_id"])
        if node["status"] == "ONLINE" and node["network_status"] == "CONNECTED":
            # Rebuild in place from a healthy peer replica.
            self.replicas.repair_replica(replica_id)
        else:
            # Node still down: place a fresh replica on another healthy node.
            sources = [
                r for r in db.query_all(
                    "SELECT * FROM replicas WHERE object_id=? AND status='HEALTHY'", (object_id,)
                )
                if self.nodes.get_node(r["node_id"])["status"] == "ONLINE"
            ]
            if not sources:
                raise ObjectNotFoundError(f"No healthy source replica for {object_id}")
            source = sources[0]
            exclude = {
                r["node_id"] for r in db.query_all(
                    "SELECT node_id FROM replicas WHERE object_id=?", (object_id,)
                )
            }
            dest = self.placement.choose_replacement_node(exclude=exclude)
            self.replicas.create_replica(
                object_id=object_id, source_node_id=source["node_id"],
                dest_node_id=dest, version=obj["version"],
            )
            with db.write() as conn:
                conn.execute("DELETE FROM replicas WHERE replica_id=?", (replica_id,))
                log_activity(
                    conn, "REPLICA_DELETED",
                    f"Unrecoverable replica on {replica['node_id']} replaced by {dest}",
                    object_id=object_id, node_id=replica["node_id"],
                )
        self._refresh_object_status(object_id)

    def _current_version(self, object_id: str) -> int:
        obj = db.query_one("SELECT version FROM objects WHERE object_id=?", (object_id,))
        return obj["version"] if obj else 1

    def _refresh_object_status(self, object_id: str) -> None:
        from backend.integrity.verifier import IntegrityVerifier

        verifier = IntegrityVerifier(store=self.store)
        verifier._update_object_status(object_id)

"""Integrity verification: compare stored bytes against expected SHA-256."""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow
from backend.exceptions import ObjectNotFoundError
from backend.integrity.checksum import bytes_sha256
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.verifier")


class IntegrityVerifier:
    def __init__(self, store: ObjectStore) -> None:
        self.store = store

    def verify_replica(self, replica: dict) -> dict:
        """Verify one replica against the authoritative object checksum."""
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (replica["object_id"],))
        if obj is None:
            raise ObjectNotFoundError(replica["object_id"])
        expected = obj["checksum"]
        node_id = replica["node_id"]

        # Unreachable node: cannot read bytes, not a corruption event.
        node = db.query_one("SELECT status, network_status FROM nodes WHERE node_id=?", (node_id,))
        if node and (node["status"] != "ONLINE" or node["network_status"] != "CONNECTED"):
            return {
                "replica_id": replica["replica_id"], "node_id": node_id,
                "status": replica["status"], "expected_checksum": expected,
                "actual_checksum": None, "detail": "node unreachable",
                "verified": False, "actionable": False,
            }

        actual = self.store.compute_checksum(node_id, replica["object_id"], replica["version"])
        verified = actual is not None and actual == expected
        return {
            "replica_id": replica["replica_id"], "node_id": node_id,
            "status": "VERIFIED" if verified else "CORRUPTED",
            "expected_checksum": expected, "actual_checksum": actual,
            "verified": verified, "actionable": True,
        }

    def verify_object(self, object_id: str, *, mark_and_schedule: bool = True) -> dict:
        """Verify all replicas of an object; optionally mark corruption and schedule repair."""
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(f"Unknown object: {object_id}")
        replicas = db.query_all("SELECT * FROM replicas WHERE object_id=?", (object_id,))
        results = [self.verify_replica(replica) for replica in replicas]

        corrupted = [r for r in results if r["actionable"] and not r["verified"]]
        verified_count = len([r for r in results if r["verified"]])

        repaired_scheduled = 0
        if mark_and_schedule:
            for item in corrupted:
                with db.write() as conn:
                    conn.execute(
                        "UPDATE replicas SET status='CORRUPTED', updated_at=? WHERE replica_id=?",
                        (utcnow(), item["replica_id"]),
                    )
                    log_activity(
                        conn, "CORRUPTION_DETECTED",
                        f"CHECKSUM MISMATCH on {item['node_id']} ({object_id})",
                        object_id=object_id, node_id=item["node_id"],
                    )
                from backend.repair.repair_manager import RepairManager

                RepairManager.instance().schedule_repair(
                    object_id=object_id, replica_id=item["replica_id"],
                    failed_node_id=item["node_id"], reason="CHECKSUM_MISMATCH",
                )
                repaired_scheduled += 1
            self._update_object_status(object_id)

        integrity = "VERIFIED" if verified_count == len(results) and results else "MISMATCH"
        if mark_and_schedule:
            with db.write() as conn:
                log_activity(
                    conn, "CHECKSUM_VERIFIED",
                    f"Integrity scan for {object_id}: {verified_count}/{len(results)} replicas verified",
                    object_id=object_id,
                )
        return {
            "object_id": object_id,
            "replicas_checked": len(results),
            "verified": verified_count,
            "corrupted": len(corrupted),
            "repaired_scheduled": repaired_scheduled,
            "integrity": integrity,
            "results": results,
        }

    def scan_cluster(self) -> dict:
        """Full-cluster integrity scan across every object."""
        object_ids = [row["object_id"] for row in db.query_all("SELECT object_id FROM objects")]
        objects = [self.verify_object(oid) for oid in object_ids]
        return {
            "objects_scanned": len(objects),
            "replicas_checked": sum(o["replicas_checked"] for o in objects),
            "verified": sum(o["verified"] for o in objects),
            "corrupted": sum(o["corrupted"] for o in objects),
            "repairs_scheduled": sum(o["repaired_scheduled"] for o in objects),
            "objects": objects,
        }

    def _update_object_status(self, object_id: str) -> None:
        """Recompute object status from its replicas (explicit state machine)."""
        replicas = db.query_all("SELECT status FROM replicas WHERE object_id=?", (object_id,))
        obj = db.query_one("SELECT status, replication_factor FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            return
        statuses = [r["status"] for r in replicas]
        reachable = db.query_all(
            "SELECT r.replica_id FROM replicas r JOIN nodes n ON n.node_id=r.node_id "
            "WHERE r.object_id=? AND r.status='HEALTHY' AND n.status='ONLINE' "
            "AND n.network_status='CONNECTED'",
            (object_id,),
        )
        if len(reachable) == 0:
            new_status = "UNAVAILABLE"
        elif len(statuses) < obj["replication_factor"] or any(s in ("MISSING", "UNAVAILABLE", "STALE") for s in statuses):
            new_status = "DEGRADED"
        elif any(s == "CORRUPTED" for s in statuses):
            new_status = "REPAIRING" if self._has_active_repair(object_id) else "CORRUPTED"
        elif any(s == "REPAIRING" for s in statuses):
            new_status = "REPAIRING"
        else:
            new_status = "HEALTHY"
        if new_status != obj["status"]:
            with db.write() as conn:
                conn.execute(
                    "UPDATE objects SET status=?, updated_at=? WHERE object_id=?",
                    (new_status, utcnow(), object_id),
                )
                log_activity(
                    conn, "OBJECT_STATUS_CHANGED",
                    f"Object {object_id} status -> {new_status}",
                    object_id=object_id,
                )

    @staticmethod
    def _has_active_repair(object_id: str) -> bool:
        return bool(
            db.query_one(
                "SELECT repair_id FROM repair_jobs WHERE object_id=? AND status IN ('QUEUED','RUNNING','VERIFYING')",
                (object_id,),
            )
        )


def bytes_sha256_reexport(payload: bytes) -> str:  # pragma: no cover
    return bytes_sha256(payload)

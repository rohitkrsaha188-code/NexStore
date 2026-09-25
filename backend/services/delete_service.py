"""Delete service: remove replicas then metadata, tolerating partial failures."""
from __future__ import annotations

import logging

from backend.database import db, log_activity, utcnow
from backend.exceptions import ObjectNotFoundError
from backend.replication.replica_manager import ReplicaManager
from backend.storage.object_store import ObjectStore

logger = logging.getLogger("vault.delete_service")


class DeleteService:
    def __init__(self, store: ObjectStore, replicas: ReplicaManager) -> None:
        self.store = store
        self.replicas = replicas

    def delete(self, object_id: str) -> dict:
        obj = db.query_one("SELECT * FROM objects WHERE object_id=?", (object_id,))
        if obj is None:
            raise ObjectNotFoundError(f"Unknown object: {object_id}")

        # Mark for deletion first so workers skip it while we tear down replicas.
        with db.write() as conn:
            conn.execute(
                "UPDATE objects SET status='DELETING', updated_at=? WHERE object_id=?",
                (utcnow(), object_id),
            )

        deleted_replicas = 0
        errors: list[str] = []
        for replica in self.replicas.list_replicas(object_id):
            try:
                self.store.delete_object(
                    replica["node_id"], replica["object_id"], replica["version"]
                )
            except OSError as exc:
                errors.append(f"{replica['node_id']}: {exc}")
            with db.write() as conn:
                conn.execute("DELETE FROM replicas WHERE replica_id=?", (replica["replica_id"],))
            deleted_replicas += 1

        with db.write() as conn:
            conn.execute("DELETE FROM replicas WHERE object_id=?", (object_id,))
            conn.execute("DELETE FROM objects WHERE object_id=?", (object_id,))
            conn.execute("DELETE FROM repair_jobs WHERE object_id=?", (object_id,))
            log_activity(
                conn, "OBJECT_DELETED",
                f"Object deleted: {obj['filename']} ({deleted_replicas} replica(s) removed)",
                object_id=object_id,
            )
        if errors:
            logger.warning("Delete %s had replica errors: %s", object_id, errors)
        return {"object_id": object_id, "filename": obj["filename"],
                "deleted_replicas": deleted_replicas, "warnings": errors}

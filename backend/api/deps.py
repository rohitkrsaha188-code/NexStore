"""Shared component wiring for the API layer (lazy singletons)."""
from __future__ import annotations

from functools import lru_cache

from backend.config import settings
from backend.replication.replica_manager import ReplicaManager
from backend.services.delete_service import DeleteService
from backend.services.download_service import DownloadService
from backend.services.upload_service import UploadService
from backend.storage.node_manager import NodeManager
from backend.storage.object_store import ObjectStore
from backend.storage.placement import PlacementPolicy


@lru_cache(maxsize=1)
def get_store() -> ObjectStore:
    return ObjectStore(settings.storage_root)


@lru_cache(maxsize=1)
def get_node_manager() -> NodeManager:
    return NodeManager(get_store())


@lru_cache(maxsize=1)
def get_placement() -> PlacementPolicy:
    return PlacementPolicy(get_store())


@lru_cache(maxsize=1)
def get_replica_manager() -> ReplicaManager:
    return ReplicaManager(get_store(), get_node_manager(), get_placement())


@lru_cache(maxsize=1)
def get_upload_service() -> UploadService:
    return UploadService(get_store(), get_node_manager(), get_placement(), get_replica_manager())


@lru_cache(maxsize=1)
def get_download_service() -> DownloadService:
    return DownloadService(get_store(), get_replica_manager())


@lru_cache(maxsize=1)
def get_delete_service() -> DeleteService:
    return DeleteService(get_store(), get_replica_manager())

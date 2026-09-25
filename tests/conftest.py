"""Shared pytest fixtures: isolated environment per test."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def vault_env(monkeypatch):
    """Redirect the DB and node storage into a temp dir (no module reloads)."""
    tmp = Path(tempfile.mkdtemp(prefix="vault_test_"))
    monkeypatch.setenv("NODE_COUNT", "5")

    import backend.config as config
    from backend.database import db as database

    db_path = tmp / "vault.db"
    storage_root = tmp / "storage_nodes"
    database.rebind(db_path)
    monkeypatch.setattr(config.settings, "storage_root", storage_root, raising=False)

    from backend.replication.replica_manager import ReplicaManager
    from backend.repair.repair_manager import RepairManager
    from backend.services.delete_service import DeleteService
    from backend.services.download_service import DownloadService
    from backend.services.upload_service import UploadService
    from backend.storage.node_manager import NodeManager
    from backend.storage.object_store import ObjectStore
    from backend.storage.placement import PlacementPolicy

    store = ObjectStore(storage_root)
    nodes = NodeManager(store)
    placement = PlacementPolicy(store)
    replicas = ReplicaManager(store, nodes, placement)

    database.initialize()
    nodes.initialize_nodes()

    from backend.integrity.verifier import IntegrityVerifier
    from backend.rebalancing.rebalancer import execute_rebalance

    container = {
        "settings": config.settings,
        "db": database,
        "store": store,
        "nodes": nodes,
        "placement": placement,
        "replicas": replicas,
        "upload": UploadService(store, nodes, placement, replicas),
        "download": DownloadService(store, replicas),
        "delete": DeleteService(store, replicas),
        "verifier": IntegrityVerifier(store),
        "repair_manager": RepairManager(store, nodes, placement, replicas),
        "execute_rebalance": execute_rebalance,
    }
    yield container

    RepairManager._instance = None
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def client(vault_env, monkeypatch):
    """TestClient with API dependencies rebound to the isolated environment."""
    import backend.api.deps as deps
    import backend.api.files as files_api
    import backend.api.nodes as nodes_api
    import backend.main as main_module

    for name, component in (
        ("get_store", vault_env["store"]),
        ("get_node_manager", vault_env["nodes"]),
        ("get_placement", vault_env["placement"]),
        ("get_replica_manager", vault_env["replicas"]),
        ("get_upload_service", vault_env["upload"]),
        ("get_download_service", vault_env["download"]),
        ("get_delete_service", vault_env["delete"]),
    ):
        monkeypatch.setattr(deps, name, (lambda comp: (lambda: comp))(component), raising=True)
    monkeypatch.setattr(files_api, "get_store", deps.get_store, raising=True)
    monkeypatch.setattr(files_api, "get_upload_service", deps.get_upload_service, raising=True)
    monkeypatch.setattr(files_api, "get_download_service", deps.get_download_service, raising=True)
    monkeypatch.setattr(files_api, "get_delete_service", deps.get_delete_service, raising=True)
    monkeypatch.setattr(nodes_api, "get_node_manager", deps.get_node_manager, raising=True)
    monkeypatch.setattr(
        main_module.RepairManager if hasattr(main_module, "RepairManager") else deps,
        "_unused", None, raising=False,
    )

    from backend.repair.repair_manager import RepairManager as RM

    monkeypatch.setattr(RM, "_instance", vault_env["repair_manager"], raising=False)

    with TestClient(main_module.app, raise_server_exceptions=False) as test_client:
        yield test_client

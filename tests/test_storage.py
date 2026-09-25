"""Tests for physical storage, placement, and node management."""
from __future__ import annotations

import hashlib

import pytest

from backend.exceptions import InsufficientNodesError


def _make_file(tmp_path, name="sample.bin", size=1024, seed=b"v"):
    path = tmp_path / name
    payload = seed * size
    path.write_bytes(payload)
    return path, len(payload)


def test_node_initialization_creates_five_nodes(vault_env):
    nodes = vault_env["nodes"].list_nodes()
    assert len(nodes) == 5
    assert all(n["status"] == "ONLINE" for n in nodes)
    assert all(n["network_status"] == "CONNECTED" for n in nodes)


def test_replica_file_written_to_node_directory(vault_env, tmp_path):
    store = vault_env["store"]
    path, size = _make_file(tmp_path)
    store.write_object("node1", "obj_test_1", 1, path)
    written = store.node_data_dir("node1") / "obj_test_1.v1"
    assert written.is_file()
    assert written.stat().st_size == size
    assert store.compute_checksum("node1", "obj_test_1", 1) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_nodes_are_isolated_directories(vault_env, tmp_path):
    store = vault_env["store"]
    path, _ = _make_file(tmp_path)
    store.write_object("node2", "obj_iso", 1, path)
    assert (store.node_data_dir("node2") / "obj_iso.v1").is_file()
    assert not (store.node_data_dir("node1") / "obj_iso.v1").exists()
    assert not (store.node_data_dir("node3") / "obj_iso.v1").exists()


def test_corrupt_replica_changes_bytes_but_not_metadata(vault_env, tmp_path):
    store = vault_env["store"]
    path, _ = _make_file(tmp_path)
    store.write_object("node1", "obj_corrupt", 1, path)
    original = store.compute_checksum("node1", "obj_corrupt", 1)
    assert store.corrupt_replica("node1", "obj_corrupt", 1) is True
    assert store.compute_checksum("node1", "obj_corrupt", 1) != original


def test_placement_returns_distinct_nodes(vault_env):
    placement = vault_env["placement"]
    chosen = placement.choose_nodes(3, object_id="obj_x")
    assert len(chosen) == 3
    assert len(set(chosen)) == 3


def test_placement_rejects_more_nodes_than_available(vault_env):
    placement = vault_env["placement"]
    with pytest.raises(InsufficientNodesError):
        placement.choose_nodes(6, object_id="obj_y")


def test_placement_excludes_failed_nodes(vault_env):
    vault_env["nodes"].fail_node("node1")
    vault_env["nodes"].fail_node("node2")
    placement = vault_env["placement"]
    chosen = placement.choose_nodes(3, object_id="obj_z")
    assert "node1" not in chosen and "node2" not in chosen


def test_fail_node_marks_replicas_unavailable(vault_env, tmp_path):
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(b"failure test")
    result = vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=12,
        content_type="application/octet-stream", replication_factor=3,
    )
    target_node = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(target_node)
    replica = vault_env["db"].query_one(
        "SELECT status FROM replicas WHERE node_id=? AND object_id=?",
        (target_node, result["object_id"]),
    )
    assert replica["status"] == "UNAVAILABLE"

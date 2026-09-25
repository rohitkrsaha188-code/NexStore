"""Node failure tests: state transitions, degraded objects, repair triggering."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import ObjectNotFoundError


def _upload(vault_env, rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(b"failure scenario")
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=16,
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_failed_node_status_and_replicas(vault_env):
    result = _upload(vault_env)
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    node = vault_env["nodes"].get_node(failed)
    assert node["status"] == "FAILED"
    assert node["network_status"] == "DISCONNECTED"
    replica = vault_env["db"].query_one(
        "SELECT status FROM replicas WHERE node_id=? AND object_id=?",
        (failed, result["object_id"]),
    )
    assert replica["status"] == "UNAVAILABLE"


def test_object_becomes_degraded_after_failure(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    vault_env["verifier"].verify_object(oid)
    obj = vault_env["db"].query_one("SELECT status FROM objects WHERE object_id=?", (oid,))
    assert obj["status"] in ("DEGRADED", "REPAIRING")


def test_failure_detection_schedules_repair(vault_env):
    result = _upload(vault_env)
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    from backend.health.failure_detector import detect_degraded_objects

    scheduled = detect_degraded_objects()
    assert any(s["object_id"] == result["object_id"] for s in scheduled)


def test_data_on_other_nodes_survives_failure(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    store = vault_env["store"]
    survivors = [n for n in result["placement"]["nodes"] if n != failed]
    vault_env["nodes"].fail_node(failed)
    for node_id in survivors:
        assert store.replica_path(node_id, oid, 1).is_file()


def test_unknown_node_action_raises(vault_env):
    from backend.exceptions import NodeNotFoundError

    with pytest.raises(NodeNotFoundError):
        vault_env["nodes"].fail_node("node99")

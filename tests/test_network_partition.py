"""Network partition tests: metadata retention, distinction from failure, recovery."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import ObjectUnavailableError


def _upload(vault_env, rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(b"partition test")
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=14,
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_partition_marks_node_partinioned(vault_env):
    result = _upload(vault_env)
    node_id = result["placement"]["nodes"][0]
    vault_env["nodes"].partition_node(node_id)
    node = vault_env["nodes"].get_node(node_id)
    assert node["status"] == "PARTITIONED"
    assert node["network_status"] == "PARTITIONED"


def test_partition_retains_metadata_and_files(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    node_id = result["placement"]["nodes"][0]
    vault_env["nodes"].partition_node(node_id)
    # Metadata survives: replica row still exists (marked UNAVAILABLE).
    replica = vault_env["db"].query_one(
        "SELECT * FROM replicas WHERE node_id=? AND object_id=?", (node_id, oid)
    )
    assert replica is not None
    # Physical file untouched on disk.
    assert vault_env["store"].replica_path(node_id, oid, 1).is_file()


def test_reads_continue_during_partition(vault_env):
    result = _upload(vault_env, rf=3)
    vault_env["nodes"].partition_node(result["placement"]["nodes"][0])
    path, meta = vault_env["download"].download(result["object_id"])
    assert path.read_bytes() == b"partition test"


def test_all_replicas_partitioned_object_unavailable(vault_env):
    result = _upload(vault_env, rf=3)
    for node_id in result["placement"]["nodes"]:
        vault_env["nodes"].partition_node(node_id)
    with pytest.raises(ObjectUnavailableError):
        vault_env["download"].download(result["object_id"])


def test_reconnect_restores_node_and_replicas(vault_env):
    result = _upload(vault_env, rf=3)
    node_id = result["placement"]["nodes"][0]
    vault_env["nodes"].partition_node(node_id)
    vault_env["nodes"].restore_node(node_id)
    node = vault_env["nodes"].get_node(node_id)
    assert node["status"] == "ONLINE"
    # Replica becomes STALE on recovery, then reconciles to HEALTHY after verify.
    from backend.replication.consistency import reconcile_stale_replicas

    reconcile_stale_replicas(result["object_id"])
    replica = vault_env["db"].query_one(
        "SELECT status FROM replicas WHERE node_id=? AND object_id=?", (node_id, result["object_id"])
    )
    assert replica["status"] == "HEALTHY"


def test_stale_replica_with_bad_data_fails_reconciliation(vault_env):
    result = _upload(vault_env, rf=3)
    oid = result["object_id"]
    node_id = result["placement"]["nodes"][0]
    vault_env["nodes"].partition_node(node_id)
    # Data silently corrupted while unreachable.
    vault_env["store"].corrupt_replica(node_id, oid, 1)
    vault_env["nodes"].restore_node(node_id)
    from backend.replication.consistency import reconcile_stale_replicas

    reconciled = reconcile_stale_replicas(oid)
    assert reconciled == []  # checksum mismatch -> not blindly trusted
    replica = vault_env["db"].query_one(
        "SELECT status FROM replicas WHERE node_id=? AND object_id=?", (node_id, oid)
    )
    assert replica["status"] == "STALE"

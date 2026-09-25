"""Corruption simulation tests: detection, metadata intact, repair scheduling."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import ReplicaNotFoundError


def _upload(vault_env, rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(b"corruption target data")
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=22,
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_corruption_detected_by_verifier(vault_env):
    result = _upload(vault_env)
    node_id = result["placement"]["nodes"][0]
    vault_env["store"].corrupt_replica(node_id, result["object_id"], 1)
    report = vault_env["verifier"].verify_object(result["object_id"])
    assert report["corrupted"] == 1
    assert report["integrity"] == "MISMATCH"


def test_corruption_keeps_metadata_checksum_intact(vault_env):
    result = _upload(vault_env)
    original_checksum = result["checksum"]
    vault_env["store"].corrupt_replica(result["placement"]["nodes"][0], result["object_id"], 1)
    obj = vault_env["db"].query_one(
        "SELECT checksum FROM objects WHERE object_id=?", (result["object_id"],)
    )
    assert obj["checksum"] == original_checksum


def test_corruption_schedules_repair(vault_env):
    result = _upload(vault_env)
    vault_env["store"].corrupt_replica(result["placement"]["nodes"][0], result["object_id"], 1)
    vault_env["verifier"].verify_object(result["object_id"])
    job = vault_env["db"].query_one(
        "SELECT * FROM repair_jobs WHERE object_id=? AND reason='CHECKSUM_MISMATCH'",
        (result["object_id"],),
    )
    assert job is not None


def test_corrupt_unknown_replica_raises(vault_env):
    with pytest.raises(ReplicaNotFoundError):
        from backend.integrity.corruption import corrupt_replica

        corrupt_replica(vault_env["store"], "rep_nonexistent")


def test_corrupted_replica_restored_to_healthy(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    node_id = result["placement"]["nodes"][0]
    vault_env["store"].corrupt_replica(node_id, oid, 1)
    vault_env["verifier"].verify_object(oid)  # detect + schedule
    vault_env["repair_manager"].run_pending_repairs()
    replica = vault_env["db"].query_one(
        "SELECT status FROM replicas WHERE node_id=? AND object_id=?", (node_id, oid)
    )
    assert replica["status"] == "HEALTHY"
    assert vault_env["store"].compute_checksum(node_id, oid, 1) == result["checksum"]

"""Download flow tests: healthy serving, failover, unavailable handling."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import ObjectUnavailableError, ObjectNotFoundError


def _upload(vault_env, payload=b"download me", rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(payload)
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=len(payload),
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_download_returns_verified_bytes(vault_env):
    payload = b"download me"
    result = _upload(vault_env, payload=payload)
    path, meta = vault_env["download"].download(result["object_id"])
    assert path.read_bytes() == payload
    assert meta["integrity"] == "VERIFIED"
    assert meta["served_from_node"] in result["placement"]["nodes"]


def test_download_unknown_object_raises(vault_env):
    with pytest.raises(ObjectNotFoundError):
        vault_env["download"].download("obj_does_not_exist")


def test_download_skips_corrupted_replica(vault_env):
    payload = b"corruption failover test"
    result = _upload(vault_env, payload=payload, rf=3)
    nodes = result["placement"]["nodes"]
    vault_env["store"].corrupt_replica(nodes[0], result["object_id"], 1)
    path, meta = vault_env["download"].download(result["object_id"])
    assert path.read_bytes() == payload
    assert meta["served_from_node"] != nodes[0]
    # Corrupted replica should have been flagged for repair.
    job = vault_env["db"].query_one(
        "SELECT * FROM repair_jobs WHERE object_id=?", (result["object_id"],)
    )
    assert job is not None


def test_download_unavailable_when_all_replicas_lost(vault_env):
    result = _upload(vault_env, rf=3)
    for node_id in result["placement"]["nodes"]:
        vault_env["nodes"].fail_node(node_id)
    with pytest.raises(ObjectUnavailableError):
        vault_env["download"].download(result["object_id"])


def test_download_marks_failed_replica_corrupted(vault_env):
    payload = b"mark corrupted"
    result = _upload(vault_env, payload=payload, rf=3)
    nodes = result["placement"]["nodes"]
    vault_env["store"].corrupt_replica(nodes[1], result["object_id"], 1)
    # Round-robin serves replicas in turn; keep reading until the corrupt one
    # is hit (it fails verification and gets marked + scheduled for repair).
    for _ in range(len(nodes) + 1):
        path, meta = vault_env["download"].download(result["object_id"])
        if meta["served_from_node"] != nodes[1] and meta["integrity"] == "VERIFIED":
            replica = vault_env["db"].query_one(
                "SELECT status FROM replicas WHERE node_id=? AND object_id=?",
                (nodes[1], result["object_id"]),
            )
            if replica["status"] == "CORRUPTED":
                break
    assert replica["status"] == "CORRUPTED"

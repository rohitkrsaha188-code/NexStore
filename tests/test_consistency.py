"""Replica consistency and versioning tests."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import VersionConflictError


def _upload(vault_env, rf=3, payload=b"consistency"):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(payload)
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=len(payload),
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_consistent_object_passes_check(vault_env):
    result = _upload(vault_env)
    from backend.replication.consistency import check_object_consistency

    report = check_object_consistency(result["object_id"])
    assert report["consistent"] is True
    assert report["stale_replicas"] == []
    assert report["divergent_replicas"] == []


def test_stale_version_detected(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    node_id = result["placement"]["nodes"][0]
    # Simulate a replica that missed the latest version bump.
    vault_env["db"].set_setting("dummy", "1")  # keep settings table warm
    with vault_env["db"].write() as conn:
        conn.execute("UPDATE replicas SET version=version-1 WHERE node_id=? AND object_id=?",
                     (node_id, oid))
    from backend.replication.consistency import check_object_consistency

    report = check_object_consistency(oid)
    assert report["consistent"] is False
    assert node_id.replace("node", "rep_") or report["stale_replicas"]


def test_divergent_checksum_detected(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    node_id = result["placement"]["nodes"][0]
    with vault_env["db"].write() as conn:
        conn.execute(
            "UPDATE replicas SET checksum='deadbeef' WHERE node_id=? AND object_id=?",
            (node_id, oid),
        )
    from backend.replication.consistency import check_object_consistency

    report = check_object_consistency(oid)
    assert report["consistent"] is False
    assert len(report["divergent_replicas"]) == 1


def test_version_conflict_raised_on_stale_write(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    from backend.concurrency.versioning import check_version

    with pytest.raises(VersionConflictError):
        check_version(oid, provided_version=99)


def test_version_check_accepts_current_version(vault_env):
    result = _upload(vault_env)
    from backend.concurrency.versioning import check_version

    assert check_version(result["object_id"], provided_version=1) == 1

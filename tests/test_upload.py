"""Upload flow tests: checksum, replication, placement, metadata."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest

from backend.exceptions import InsufficientNodesError


def _upload(vault_env, name="file.bin", payload=b"hello vault", rf=3):
    tmp = Path(tempfile.mkdtemp()) / "payload.bin"
    tmp.write_bytes(payload)
    return vault_env["upload"].upload(
        filename=name, tmp_path=tmp, size=len(payload),
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_upload_creates_object_metadata(vault_env):
    result = _upload(vault_env)
    obj = vault_env["db"].query_one(
        "SELECT * FROM objects WHERE object_id=?", (result["object_id"],)
    )
    assert obj is not None
    assert obj["filename"] == "file.bin"
    assert obj["checksum"] == hashlib.sha256(b"hello vault").hexdigest()
    assert obj["replication_factor"] == 3
    assert obj["status"] == "HEALTHY"


def test_upload_creates_requested_replicas(vault_env):
    result = _upload(vault_env, rf=3)
    replicas = vault_env["db"].query_all(
        "SELECT * FROM replicas WHERE object_id=?", (result["object_id"],)
    )
    assert len(replicas) == 3
    assert len({r["node_id"] for r in replicas}) == 3
    assert all(r["status"] == "HEALTHY" for r in replicas)


def test_upload_replica_files_exist_on_nodes(vault_env):
    result = _upload(vault_env, rf=3)
    store = vault_env["store"]
    for node_id in result["placement"]["nodes"]:
        path = store.replica_path(node_id, result["object_id"], 1)
        assert path.is_file()
        assert store.compute_checksum(node_id, result["object_id"], 1) == result["checksum"]


def test_upload_respects_custom_replication_factor(vault_env):
    result = _upload(vault_env, rf=2)
    assert result["replication_factor"] == 2
    assert len(result["placement"]["nodes"]) == 2


def test_upload_rejects_rf_greater_than_healthy_nodes(vault_env):
    for node_id in ("node1", "node2", "node3"):
        vault_env["nodes"].fail_node(node_id)
    with pytest.raises(InsufficientNodesError):
        _upload(vault_env, rf=3)


def test_upload_sanitizes_path_traversal_filename(vault_env):
    result = _upload(vault_env, name=".._.._etc_passwd")
    # No separators and no leading dots: value can never traverse paths.
    assert "/" not in result["filename"]
    assert not result["filename"].startswith(".")
    assert result["filename"] == "_.._etc_passwd"


def test_upload_rejects_empty_filename(vault_env):
    import io
    from backend.exceptions import InvalidFilenameError as _IFE

    tmp = Path(tempfile.mkdtemp()) / "blank.bin"
    tmp.write_bytes(b"x")  # file content exists; the NAME is what gets rejected
    with pytest.raises(_IFE):
        vault_env["upload"].upload(
            filename="   ", tmp_path=tmp, size=1,
            content_type="application/octet-stream", replication_factor=1,
        )


def test_upload_writes_activity_log(vault_env):
    result = _upload(vault_env)
    row = vault_env["db"].query_one(
        "SELECT * FROM activity_logs WHERE event_type='OBJECT_UPLOADED' AND object_id=?",
        (result["object_id"],),
    )
    assert row is not None

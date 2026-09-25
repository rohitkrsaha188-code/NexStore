"""Delete flow tests: replicas removed from disk and metadata."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import ObjectNotFoundError


def _upload(vault_env, payload=b"to be deleted", rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(payload)
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=len(payload),
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_delete_removes_object_and_replicas(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    store = vault_env["store"]
    summary = vault_env["delete"].delete(oid)
    assert summary["deleted_replicas"] == 3
    assert vault_env["db"].query_one("SELECT * FROM objects WHERE object_id=?", (oid,)) is None
    assert vault_env["db"].query_all("SELECT * FROM replicas WHERE object_id=?", (oid,)) == []
    for node_id in result["placement"]["nodes"]:
        assert not store.replica_path(node_id, oid, 1).exists()


def test_delete_unknown_object_raises(vault_env):
    with pytest.raises(ObjectNotFoundError):
        vault_env["delete"].delete("obj_missing")


def test_delete_survives_node_failure(vault_env):
    """Deleting an object with one node down must still purge metadata."""
    result = _upload(vault_env, rf=3)
    oid = result["object_id"]
    nodes = result["placement"]["nodes"]
    vault_env["nodes"].fail_node(nodes[0])
    summary = vault_env["delete"].delete(oid)
    assert vault_env["db"].query_one("SELECT * FROM objects WHERE object_id=?", (oid,)) is None
    assert summary["deleted_replicas"] == 3


def test_delete_writes_activity_event(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    vault_env["delete"].delete(oid)
    row = vault_env["db"].query_one(
        "SELECT * FROM activity_logs WHERE event_type='OBJECT_DELETED' AND object_id=?", (oid,)
    )
    assert row is not None

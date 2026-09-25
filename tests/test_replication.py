"""Replication tests: placement policy, replica records, node uniqueness."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.exceptions import InsufficientNodesError


def _upload(vault_env, rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(b"replicate")
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=9,
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_replicas_never_share_a_node(vault_env):
    result = _upload(vault_env, rf=3)
    nodes = [r["node_id"] for r in result["replicas"]]
    assert len(nodes) == len(set(nodes))


def test_rf_one_places_single_replica(vault_env):
    result = _upload(vault_env, rf=1)
    assert len(result["replicas"]) == 1


def test_rf_equal_to_node_count_succeeds(vault_env):
    result = _upload(vault_env, rf=5)
    assert len(result["replicas"]) == 5


def test_rf_beyond_node_count_fails(vault_env):
    with pytest.raises(InsufficientNodesError):
        _upload(vault_env, rf=6)


def test_repair_restores_replica_count_after_failure(vault_env):
    result = _upload(vault_env, rf=3)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    scheduled = vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    assert scheduled, "repair should be scheduled"
    vault_env["repair_manager"].run_pending_repairs()
    replicas = vault_env["db"].query_all("SELECT * FROM replicas WHERE object_id=?", (oid,))
    healthy = [r for r in replicas if r["status"] == "HEALTHY"]
    assert len(healthy) == 3
    assert failed not in [r["node_id"] for r in healthy]


def test_repair_replaces_failed_node_replica_on_new_node(vault_env):
    result = _upload(vault_env, rf=3)
    oid = result["object_id"]
    original_nodes = set(result["placement"]["nodes"])
    failed = result["placement"]["nodes"][1]
    vault_env["nodes"].fail_node(failed)
    vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    vault_env["repair_manager"].run_pending_repairs()
    new_nodes = {
        r["node_id"]
        for r in vault_env["db"].query_all("SELECT * FROM replicas WHERE object_id=?", (oid,))
    }
    assert failed not in new_nodes
    assert original_nodes - {failed} <= new_nodes
    assert len(new_nodes - original_nodes) == 1  # exactly one replacement node


def test_no_duplicate_repair_jobs_for_same_replica(vault_env):
    result = _upload(vault_env, rf=3)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    first = vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    second = vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    # Second pass must not duplicate work for replicas already queued/repaired.
    assert len(second) == 0 or set(second).isdisjoint(set(first)) or second == []

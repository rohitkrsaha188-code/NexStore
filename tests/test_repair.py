"""Repair pipeline tests: queue idempotency, worker execution, replacement."""
from __future__ import annotations

import tempfile
from pathlib import Path


def _upload(vault_env, rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(b"repair pipeline data")
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=20,
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_repair_job_lifecycle(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    jobs = vault_env["db"].query_all("SELECT * FROM repair_jobs WHERE object_id=?", (oid,))
    assert jobs, "job must be queued"
    assert any(j["status"] == "QUEUED" for j in jobs)
    vault_env["repair_manager"].run_pending_repairs()
    jobs = vault_env["db"].query_all("SELECT * FROM repair_jobs WHERE object_id=?", (oid,))
    assert all(j["status"] == "COMPLETED" for j in jobs)
    assert all(j["duration_ms"] is not None for j in jobs)


def test_repair_verified_before_complete(vault_env):
    """A repair whose result fails checksum must not be marked healthy."""
    result = _upload(vault_env)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    # Sabotage the surviving sources so the repair cannot produce valid data.
    for node_id in result["placement"]["nodes"][1:]:
        vault_env["store"].corrupt_replica(node_id, oid, 1)
    vault_env["repair_manager"].run_pending_repairs()
    jobs = vault_env["db"].query_all(
        "SELECT * FROM repair_jobs WHERE object_id=? AND status='FAILED'", (oid,)
    )
    assert jobs, "repair with bad sources must fail, not fake success"


def test_repair_replaces_replica_when_node_still_down(vault_env):
    result = _upload(vault_env)
    oid = result["object_id"]
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    vault_env["repair_manager"].schedule_missing_replicas(object_id=oid, desired=3)
    vault_env["repair_manager"].run_pending_repairs()
    rows = vault_env["db"].query_all("SELECT * FROM replicas WHERE object_id=?", (oid,))
    assert failed not in [r["node_id"] for r in rows]
    assert len([r for r in rows if r["status"] == "HEALTHY"]) == 3


def test_repair_records_duration_metric(vault_env):
    result = _upload(vault_env)
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)
    vault_env["repair_manager"].schedule_missing_replicas(
        object_id=result["object_id"], desired=3
    )
    vault_env["repair_manager"].run_pending_repairs()
    avg = vault_env["db"].scalar(
        "SELECT AVG(duration_ms) FROM repair_jobs WHERE status='COMPLETED'"
    )
    assert avg is not None

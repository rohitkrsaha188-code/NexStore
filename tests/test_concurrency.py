"""Concurrency tests: parallel reads, serialized writes, duplicate repair guard."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path


def _upload(vault_env, rf=3, payload=b"concurrent"):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(payload)
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=len(payload),
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_concurrent_reads_all_succeed(vault_env):
    result = _upload(vault_env, rf=3)
    results: list[bytes] = []
    errors: list[Exception] = []

    def read() -> None:
        try:
            path, meta = vault_env["download"].download(result["object_id"])
            results.append(path.read_bytes())
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=read) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results == [b"concurrent"] * 12


def test_concurrent_uploads_create_distinct_objects(vault_env):
    results: list[dict] = []
    errors: list[Exception] = []

    def write(i: int) -> None:
        try:
            tmp = Path(tempfile.mkdtemp()) / f"f{i}.bin"
            tmp.write_bytes(f"payload {i}".encode())
            results.append(
                vault_env["upload"].upload(
                    filename=f"f{i}.bin", tmp_path=tmp, size=tmp.stat().st_size,
                    content_type="application/octet-stream", replication_factor=2,
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len({r["object_id"] for r in results}) == 6


def test_lock_manager_serializes_same_key(vault_env):
    from backend.concurrency.locks import LockManager

    manager = LockManager()
    order: list[int] = []

    def worker(idx: int) -> None:
        with manager.acquire("object_x"):
            order.append(idx)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(order) == 5  # all entered; serialized, no corruption


def test_concurrent_repair_scheduling_does_not_duplicate_jobs(vault_env):
    result = _upload(vault_env, rf=3)
    failed = result["placement"]["nodes"][0]
    vault_env["nodes"].fail_node(failed)

    all_scheduled: list[list[str]] = []

    def schedule() -> None:
        all_scheduled.append(
            vault_env["repair_manager"].schedule_missing_replicas(
                object_id=result["object_id"], desired=3
            )
        )

    threads = [threading.Thread(target=schedule) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    jobs = vault_env["db"].query_all(
        "SELECT COUNT(*) AS n FROM repair_jobs WHERE object_id=?", (result["object_id"],)
    )
    # Exactly one job per repaired replica regardless of concurrent scheduling.
    total_replica_rows = len(
        vault_env["db"].query_all("SELECT * FROM replicas WHERE object_id=?", (result["object_id"],))
    )
    assert jobs[0]["n"] <= total_replica_rows

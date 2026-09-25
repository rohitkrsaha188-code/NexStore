"""Integrity verification tests: SHA-256 match/mismatch, cluster scan."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path


def _upload(vault_env, payload=b"integrity check payload", rf=3):
    tmp = Path(tempfile.mkdtemp()) / "f.bin"
    tmp.write_bytes(payload)
    return vault_env["upload"].upload(
        filename="f.bin", tmp_path=tmp, size=len(payload),
        content_type="application/octet-stream", replication_factor=rf,
    )


def test_upload_checksum_is_sha256_of_content(vault_env):
    payload = b"sha256 sanity"
    result = _upload(vault_env, payload=payload)
    assert result["checksum"] == hashlib.sha256(payload).hexdigest()


def test_verify_all_healthy_replicas(vault_env):
    result = _upload(vault_env)
    report = vault_env["verifier"].verify_object(result["object_id"])
    assert report["verified"] == 3
    assert report["corrupted"] == 0
    assert report["integrity"] == "VERIFIED"


def test_verify_reports_actual_checksum_on_mismatch(vault_env):
    result = _upload(vault_env)
    node_id = result["placement"]["nodes"][0]
    vault_env["store"].corrupt_replica(node_id, result["object_id"], 1)
    report = vault_env["verifier"].verify_object(result["object_id"])
    bad = [r for r in report["results"] if not r["verified"]]
    assert len(bad) == 1
    assert bad[0]["node_id"] == node_id
    assert bad[0]["actual_checksum"] is not None
    assert bad[0]["actual_checksum"] != bad[0]["expected_checksum"]


def test_verify_unknown_object_raises(vault_env):
    from backend.exceptions import ObjectNotFoundError

    try:
        vault_env["verifier"].verify_object("obj_missing")
        assert False, "expected ObjectNotFoundError"
    except ObjectNotFoundError:
        pass


def test_cluster_scan_covers_all_objects(vault_env):
    _upload(vault_env, payload=b"object one")
    _upload(vault_env, payload=b"object two")
    scan = vault_env["verifier"].scan_cluster()
    assert scan["objects_scanned"] == 2
    assert scan["replicas_checked"] == 6
    assert scan["corrupted"] == 0

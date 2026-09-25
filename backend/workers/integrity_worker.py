"""Integrity worker: periodic cluster-wide SHA-256 verification."""
from __future__ import annotations

import asyncio
import logging

from backend.database import get_setting_int
from backend.integrity.verifier import IntegrityVerifier
from backend.storage.object_store import ObjectStore
from backend.config import settings

logger = logging.getLogger("vault.integrity_worker")


async def integrity_worker_loop(default_interval: int) -> None:
    logger.info("Integrity worker started (interval=%ds)", default_interval)
    while True:
        try:
            interval = get_setting_int("integrity_check_interval", default_interval)
            verifier = IntegrityVerifier(store=ObjectStore(settings.storage_root))
            result = verifier.scan_cluster()
            if result["corrupted"]:
                logger.warning(
                    "Integrity scan found %d corrupted replica(s); repairs scheduled",
                    result["corrupted"],
                )
        except Exception:  # noqa: BLE001
            logger.exception("Integrity worker iteration failed")
        await asyncio.sleep(interval)

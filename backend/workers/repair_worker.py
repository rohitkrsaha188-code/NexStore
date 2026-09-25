"""Repair worker loop: drains the repair queue periodically."""
from __future__ import annotations

import asyncio
import logging

from backend.database import get_setting_int
from backend.repair.repair_manager import RepairManager

logger = logging.getLogger("vault.repair_worker")


async def repair_worker_loop(default_interval: int) -> None:
    logger.info("Repair worker started (interval=%ds)", default_interval)
    while True:
        try:
            interval = get_setting_int("repair_interval", default_interval)
            manager = RepairManager.instance()
            processed = manager.run_pending_repairs()
            if processed:
                logger.info("Repair worker processed %d job(s)", processed)
        except Exception:  # noqa: BLE001
            logger.exception("Repair worker iteration failed")
        await asyncio.sleep(interval)

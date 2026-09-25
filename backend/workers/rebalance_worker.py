"""Rebalance worker: periodically balance node utilization."""
from __future__ import annotations

import asyncio
import logging

from backend.config import settings
from backend.database import get_setting_int
from backend.rebalancing.rebalancer import execute_rebalance

logger = logging.getLogger("vault.rebalance_worker")


async def rebalance_worker_loop(default_interval: int) -> None:
    logger.info("Rebalance worker started (interval=%ds)", default_interval)
    while True:
        try:
            threshold = get_setting_int("rebalance_threshold", settings.rebalance_threshold)
            from backend.repair.repair_manager import RepairManager

            replicas = RepairManager.instance()
            result = execute_rebalance(replicas, threshold, max_moves=3)
            if result["planned"]:
                logger.info(
                    "Rebalance: %d move(s) completed, %d failed",
                    result["completed"], result["failed"],
                )
        except Exception:  # noqa: BLE001
            logger.exception("Rebalance worker iteration failed")
        await asyncio.sleep(get_setting_int("integrity_check_interval", default_interval))

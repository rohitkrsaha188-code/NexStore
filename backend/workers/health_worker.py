"""Health worker: periodic heartbeat refresh, timeout detection, repair scheduling."""
from __future__ import annotations

import asyncio
import logging

from backend.database import get_setting_int
from backend.health.failure_detector import detect_degraded_objects
from backend.health.health_checker import run_health_check

logger = logging.getLogger("vault.health_worker")


async def health_worker_loop(default_interval: int) -> None:
    logger.info("Health worker started (interval=%ds)", default_interval)
    while True:
        try:
            interval = get_setting_int("health_check_interval", default_interval)
            result = run_health_check(heartbeat_timeout=interval * 3)
            scheduled = detect_degraded_objects()
            if scheduled:
                logger.info("Health worker scheduled %d repair job(s)", len(scheduled))
        except Exception:  # noqa: BLE001
            logger.exception("Health worker iteration failed")
        await asyncio.sleep(interval)

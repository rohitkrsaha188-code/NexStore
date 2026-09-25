#!/usr/bin/env python3
"""Run VAULT: python run.py (defaults to 127.0.0.1:8000)."""
from __future__ import annotations

import uvicorn

from backend.config import settings
from backend.logging_config import configure_logging


def main() -> None:
    configure_logging()
    print(f"Starting {settings.app_name} on http://{settings.host}:{settings.port}")
    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()

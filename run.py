#!/usr/bin/env python3
"""Run VAULT: python run.py (defaults to 127.0.0.1:8000)."""
from __future__ import annotations

import os
import ssl
import sys

import uvicorn


# python.org macOS builds ship without CA certificates unless
# "Install Certificates.command" was run; fall back to system trust store.
if sys.platform == "darwin" and not ssl.get_default_verify_paths().cafile:
    try:
        import certifi

        os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    except ImportError:
        os.environ["SSL_CERT_FILE"] = "/etc/ssl/cert.pem"

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

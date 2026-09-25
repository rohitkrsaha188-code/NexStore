"""Application configuration loaded from environment variables with sensible defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no external dependency). Existing env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_ROOT / ".env")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    app_name: str = os.environ.get("APP_NAME") or "NexStore"
    host: str = os.environ.get("HOST") or "127.0.0.1"
    # PORT=0/empty comes from ambient environments (CI sandboxes); it is never
    # a valid listen port for VAULT, so fall back to the default.
    port: int = _int_env("PORT", 8000) or 8000

    replication_factor: int = _int_env("REPLICATION_FACTOR", 3)
    health_check_interval: int = _int_env("HEALTH_CHECK_INTERVAL", 5)
    heartbeat_timeout: int = _int_env("HEARTBEAT_TIMEOUT", 15)
    repair_interval: int = _int_env("REPAIR_INTERVAL", 5)
    integrity_check_interval: int = _int_env("INTEGRITY_CHECK_INTERVAL", 30)
    rebalance_threshold: int = _int_env("REBALANCE_THRESHOLD", 80)
    max_storage_per_node: int = _int_env("MAX_STORAGE_PER_NODE", 10 * 1024**3)
    max_upload_size: int = _int_env("MAX_UPLOAD_SIZE", 512 * 1024**2)

    node_count: int = _int_env("NODE_COUNT", 5)
    data_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data")
    # VAULT_DB_PATH / VAULT_STORAGE_ROOT let tests isolate filesystem state.
    storage_root: Path = field(
        default_factory=lambda: Path(os.environ.get("VAULT_STORAGE_ROOT") or PROJECT_ROOT / "storage_nodes")
    )
    db_path: Path = field(
        default_factory=lambda: Path(os.environ.get("VAULT_DB_PATH") or PROJECT_ROOT / "data" / "vault.db")
    )
    log_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "logs")

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.storage_root.mkdir(parents=True, exist_ok=True)


settings = Settings()

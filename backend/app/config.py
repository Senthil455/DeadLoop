"""Environment-driven application configuration.

Secrets are read from the environment only. They are never written to the
database, returned by the API, or included in logs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
DEFAULT_DB_PATH = BACKEND_DIR / "data" / "deadloop.db"
DEV_ADMIN_TOKEN = "dev-admin-token"


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [part.strip() for part in raw.split(",") if part.strip()]


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


@dataclass(frozen=True)
class Settings:
    environment: str = field(default_factory=lambda: os.getenv("DEADLOOP_ENV", "development"))
    database_url: str = field(
        default_factory=lambda: os.getenv("DEADLOOP_DATABASE_URL", "").strip()
        or _sqlite_url(DEFAULT_DB_PATH)
    )
    admin_token: str = field(
        default_factory=lambda: os.getenv("DEADLOOP_ADMIN_TOKEN", DEV_ADMIN_TOKEN)
    )
    cors_origins: list[str] = field(
        default_factory=lambda: _csv(
            "DEADLOOP_CORS_ORIGINS",
            [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
            ],
        )
    )
    max_request_bytes: int = field(
        default_factory=lambda: _int("DEADLOOP_MAX_REQUEST_BYTES", 256 * 1024)
    )
    max_batch_size: int = field(default_factory=lambda: _int("DEADLOOP_MAX_BATCH_SIZE", 100))
    auto_create_schema: bool = field(
        default_factory=lambda: _bool("DEADLOOP_AUTO_CREATE", True)
    )
    frontend_dist: Path = field(
        default_factory=lambda: Path(
            os.getenv("DEADLOOP_FRONTEND_DIST", PROJECT_ROOT / "frontend" / "dist")
        )
    )

    @property
    def ai_enabled(self) -> bool:
        return _bool("DEADLOOP_AI_ENABLED", False)

    @property
    def ai_base_url(self) -> str:
        return os.getenv("DEADLOOP_AI_BASE_URL", "").strip()

    @property
    def ai_model(self) -> str:
        return os.getenv("DEADLOOP_AI_MODEL", "").strip()

    @property
    def ai_api_key(self) -> str:
        return os.getenv("DEADLOOP_AI_API_KEY", "").strip()

    @property
    def ai_timeout_seconds(self) -> float:
        raw = os.getenv("DEADLOOP_AI_TIMEOUT_SECONDS", "12")
        try:
            return max(1.0, min(60.0, float(raw)))
        except ValueError:
            return 12.0

    def validate_runtime(self) -> None:
        if self.environment.lower() == "production" and self.admin_token == DEV_ADMIN_TOKEN:
            raise RuntimeError(
                "DEADLOOP_ADMIN_TOKEN must be set to a strong, unique value in production."
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

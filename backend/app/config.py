"""Environment-driven application configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./queueforge.db")
    auth_enabled: bool = _bool("AUTH_ENABLED", False)
    auto_create_schema: bool = _bool("AUTO_CREATE_SCHEMA", True)
    bootstrap_api_key: str = os.getenv("BOOTSTRAP_API_KEY", "")
    cors_origins: tuple[str, ...] = tuple(x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip())
    default_tenant_id: str = os.getenv("DEFAULT_TENANT_ID", "demo")
    default_tenant_name: str = os.getenv("DEFAULT_TENANT_NAME", "Nexus Labs")
    lease_seconds: int = max(10, int(os.getenv("LEASE_SECONDS", "30")))
    max_payload_bytes: int = max(1024, int(os.getenv("MAX_PAYLOAD_BYTES", "65536")))
    max_sleep_seconds: float = min(60.0, max(0.0, float(os.getenv("MAX_SLEEP_SECONDS", "15"))))


settings = Settings()


def validate_runtime_config() -> None:
    """Fail fast on unsafe production settings instead of serving a false green health check."""
    if settings.app_env not in {"production", "prod"}:
        return
    problems: list[str] = []
    if not settings.auth_enabled:
        problems.append("AUTH_ENABLED must be true")
    if not settings.bootstrap_api_key or len(settings.bootstrap_api_key) < 32:
        problems.append("BOOTSTRAP_API_KEY must contain at least 32 characters")
    if settings.database_url.startswith("sqlite"):
        problems.append("DATABASE_URL must point to PostgreSQL for production")
    if settings.auto_create_schema:
        problems.append("AUTO_CREATE_SCHEMA must be false; use Alembic migrations")
    if not settings.cors_origins or "*" in settings.cors_origins:
        problems.append("CORS_ORIGINS must explicitly list trusted origins")
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))

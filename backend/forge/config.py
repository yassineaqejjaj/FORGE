"""Application settings (environment variables prefixed with ``FORGE_``, docs/ARCHITECTURE.md §1)."""

from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forge import __version__

#: Development-only secrets. Refused when ``FORGE_ENV=production``.
DEV_JWT_SECRET = "forge-dev-secret-change-me-0123456789abcdef"
DEV_SECRETS_KEY = "forge-dev-secrets-key-change-me-0123456789"

_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FORGE_",
        env_file=(str(_BACKEND_DIR.parent / ".env"), str(_BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Runtime -------------------------------------------------------------------------------
    env: Literal["development", "production", "test"] = "development"
    log_level: str = "INFO"
    app_version: str = __version__
    #: Public URL of the API (shown in the UI for OTLP / CI snippets).
    public_base_url: str = "http://localhost:8100"

    # --- Infrastructure ------------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://forge:forge@postgres:5432/forge"
    database_pool_size: int = 10
    database_max_overflow: int = 10
    valkey_url: str = "redis://valkey:6379/0"

    # --- Security --------------------------------------------------------------------------------
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = Field(default=720, ge=5, le=60 * 24 * 30)
    cookie_secure: bool = False
    #: Master key for provider credentials and agent secrets (Fernet key derived with SHA-256).
    secrets_key: str = DEV_SECRETS_KEY
    login_rate_limit_per_minute: int = 10

    # --- Observability (FORGE's own telemetry) ---------------------------------------------------
    otlp_endpoint: str = ""
    otlp_headers: str = ""
    service_name: str = "forge-api"

    # --- Trace ingestion (agents → FORGE) --------------------------------------------------------
    otlp_ingest_max_bytes: int = 10 * 1024 * 1024
    #: Seconds the runner waits after the agent answered for late OTLP spans before evaluating.
    trace_grace_seconds: float = 2.0
    max_output_chars: int = 200_000
    max_event_payload_chars: int = 20_000

    # --- Runner ----------------------------------------------------------------------------------
    runner_default_timeout_seconds: float = 120.0
    #: Default max concurrent calls per agent version across all workers (Valkey semaphore).
    runner_default_concurrency: int = 4
    #: Default requests per minute per judge/provider credential (Valkey sliding window).
    provider_rate_limit_per_minute: int = 120

    # --- Evaluation ------------------------------------------------------------------------------
    judge_cache_enabled: bool = True
    judge_timeout_seconds: float = 90.0
    judge_max_retries: int = 2
    #: Optional LLM used to synthesise feedback reports (OpenAI-compatible). Deterministic otherwise.
    feedback_llm_base_url: str = ""
    feedback_llm_model: str = ""
    feedback_llm_api_key: str = ""

    # --- Integrations ----------------------------------------------------------------------------
    orbit_base_url: str = ""
    demo_agents_url: str = "http://demo-agents:8190"
    #: Optional provider keys imported as credentials at bootstrap (never logged).
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    openai_judge_model: str = "gpt-5-mini"
    anthropic_judge_model: str = "claude-haiku-4-5-20251001"

    # --- Bootstrap -------------------------------------------------------------------------------
    bootstrap_admin_email: str = "admin@forge.local"
    bootstrap_admin_password: str = "forge-admin"
    bootstrap_admin_name: str = "Administrateur FORGE"

    # --- Worker ----------------------------------------------------------------------------------
    #: Comma-separated queues handled by this worker: ``execution``, ``evaluation`` or both.
    worker_queues: str = "execution,evaluation"
    worker_concurrency: int = Field(default=4, ge=1, le=64)
    worker_poll_interval_seconds: float = 0.5
    worker_heartbeat_seconds: float = 30.0
    worker_job_timeout_seconds: float = 900.0
    worker_stale_lock_seconds: float = 1200.0
    worker_shutdown_grace_seconds: float = 30.0
    worker_metrics_port: int = 9464  # 0 disables the worker Prometheus endpoint

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()

    @field_validator(
        "otlp_endpoint",
        "orbit_base_url",
        "demo_agents_url",
        "public_base_url",
        "feedback_llm_base_url",
        "openai_base_url",
    )
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @model_validator(mode="after")
    def _check_production_secrets(self) -> Settings:
        if self.env == "production":
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError(
                    "FORGE_JWT_SECRET doit être défini (≥ 32 caractères) lorsque FORGE_ENV=production."
                )
            if self.secrets_key == DEV_SECRETS_KEY or len(self.secrets_key) < 32:
                raise ValueError(
                    "FORGE_SECRETS_KEY doit être défini (≥ 32 caractères) lorsque FORGE_ENV=production."
                )
            if self.bootstrap_admin_password == "forge-admin":
                raise ValueError(
                    "FORGE_BOOTSTRAP_ADMIN_PASSWORD doit être changé lorsque FORGE_ENV=production."
                )
        return self

    # --- Derived values ---------------------------------------------------------------------------
    @property
    def fernet_key(self) -> bytes:
        return base64.urlsafe_b64encode(hashlib.sha256(self.secrets_key.encode("utf-8")).digest())

    @property
    def queues(self) -> list[str]:
        return [q.strip() for q in self.worker_queues.split(",") if q.strip()]

    @property
    def session_ttl_seconds(self) -> int:
        return self.jwt_ttl_minutes * 60

    @property
    def feedback_llm_enabled(self) -> bool:
        return bool(self.feedback_llm_base_url and self.feedback_llm_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

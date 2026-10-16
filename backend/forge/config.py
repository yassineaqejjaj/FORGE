"""Application settings (environment variables prefixed with ``FORGE_``, docs/ARCHITECTURE.md §1)."""

from __future__ import annotations

import base64
import hashlib
import os
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
    #: Commit deployed (``/health``, ``/ready``): ``FORGE_GIT_SHA``, else the ``GIT_SHA`` build argument,
    #: else Railway's ``RAILWAY_GIT_COMMIT_SHA`` (first non-empty).
    git_sha: str = ""
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

    #: ORION workspace isolation (NOV-105, docs/WORKSPACES.md). ``off`` (default): the workspace columns
    #: exist and are stamped, nothing is filtered or counted — behaviour identical to before. ``shadow``:
    #: every read of a row outside the caller's workspace is logged and counted
    #: (``forge_workspace_violations_total``) but still served. ``enforce``: such rows are invisible (404,
    #: indistinguishable from an unknown id).
    workspace_enforcement: Literal["off", "shadow", "enforce"] = "off"

    # --- OIDC relying party (NOV-108, docs/OIDC.md) — everything off by default ---------------------
    #: ``False`` (default): no OIDC route is mounted and no Bearer token is read as an IdP token; password,
    #: local JWT and ``fgk_…`` keys behave exactly as before.
    oidc_enabled: bool = False
    #: Issuer (``iss``) of the ORION realm, e.g. ``https://idp.example/realms/orion``. Required when enabled.
    oidc_issuer: str = ""
    oidc_client_id: str = "forge"
    #: Client secret of a confidential client (``client_secret_post``); empty for a public PKCE client.
    oidc_client_secret: str = ""
    #: ``aud`` FORGE accepts (ADR §3: one token per audience).
    oidc_audience: str = "forge"
    #: Endpoints; default to the Keycloak layout under the issuer.
    oidc_authorization_endpoint: str = ""
    oidc_token_endpoint: str = ""
    oidc_jwks_url: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_jwks_cache_seconds: float = Field(default=300.0, ge=0.0)
    #: Minimum delay between two JWKS refreshes forced by an unknown ``kid`` (key rotation, flood guard).
    oidc_jwks_min_refresh_seconds: float = Field(default=30.0, ge=0.0)
    oidc_clock_leeway_seconds: float = Field(default=30.0, ge=0.0, le=300.0)
    #: Longest life of a FORGE session opened by SSO (the IdP token is not stored or refreshed).
    oidc_session_ttl_minutes: int = Field(default=60, ge=5, le=60 * 24)
    #: ``False`` (default): an SSO identity with no local account is refused. ``True``: created (viewer-level
    #: local rights, workspace of the token) when the e-mail is verified.
    oidc_auto_provision: bool = False
    #: ADR §8 phase 3: linked users can no longer log in with their password (break-glass admins always can).
    password_login_disabled_for_linked: bool = False
    #: Administrators (e-mail, comma separated) that always keep the password login. The bootstrap
    #: administrator is always one.
    break_glass_emails: str = ""
    #: ``True``: an administrator authenticated by SSO needs ``amr`` ∋ ``mfa`` for admin operations.
    require_mfa_for_admin: bool = False

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

    #: LLM guardrail: highest classification (0-3) that may leave FORGE for an LLM (judges, feedback
    #: synthesis, OpenAI/Anthropic agent adapters). Same policy and default (C1) as ORBIT.
    llm_max_classification: int = Field(default=1, ge=0, le=3)
    #: True when every LLM is self-hosted: lifts the ceiling (same as ORBIT's ``ORBIT_LLM_LOCAL``).
    llm_local: bool = False

    # --- Retention (docs/OPERATIONS.md) -------------------------------------------------------------
    #: Days after which the *text* FORGE copied is emptied (0 keeps it forever). Scores, errors, costs,
    #: latencies and the timeline structure are never purged: they are the measurement.
    retention_trace_days: int = Field(default=180, ge=0)  # execution traces + trace event payloads
    retention_evaluation_days: int = Field(default=180, ge=0)  # judge prompts / answers (raw_response)
    retention_judge_cache_days: int = Field(default=90, ge=0)  # judge cache rows (deleted)
    retention_feedback_days: int = Field(default=365, ge=0)  # evidence / examples of feedback reports
    #: Hours between two scheduled purges run by the workers (0 disables the schedule).
    retention_interval_hours: float = Field(default=24.0, ge=0.0)
    #: Scheduled purge only counts what it would purge (the CLI ``--dry-run`` does the same on demand).
    retention_dry_run: bool = False
    #: Shared secret of the signed ORBIT webhook (``POST /api/v1/webhooks/orbit``); empty = refused.
    orbit_webhook_secret: str = ""

    # --- Promotion policy ------------------------------------------------------------------------
    #: ``strict`` (default): an experiment cannot start, pass the CI gate or be published as a learning
    #: unless its judges are calibrated on a gold set, its agent versions are free of contamination and
    #: the regression cases of the agent are replayed (the gate then passes on ``ship`` only).
    #: ``warn``: the same findings are reported as warnings and block nothing.
    promotion_policy: Literal["strict", "warn"] = "strict"
    #: Minimum weighted kappa of a judge against human scores on gold datasets (strict policy).
    calibration_min_kappa: float = Field(default=0.6, ge=0.0, le=1.0)

    # --- Analytics (benchmarks, experiments) -----------------------------------------------------
    #: Bootstrap resamples of the confidence intervals (seeded, docs §9.3).
    analytics_bootstrap_resamples: int = Field(default=10_000, ge=100, le=100_000)
    #: Upper bound of runs created by one benchmark launch or one experiment (N × M × K).
    analytics_max_runs_per_launch: int = Field(default=5_000, ge=1)

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

    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        """Accept PaaS-style URLs (``postgres://`` / ``postgresql://``, e.g. Railway, Heroku)."""
        value = value.strip()
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+asyncpg://" + value[len(prefix) :]
        return value

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
    def _check_oidc(self) -> Settings:
        if self.oidc_enabled:
            if not self.oidc_issuer.strip():
                raise ValueError("FORGE_OIDC_ISSUER est requis lorsque FORGE_OIDC_ENABLED=true.")
            issuer = self.oidc_issuer.strip().rstrip("/")
            self.oidc_issuer = issuer
            base = f"{issuer}/protocol/openid-connect"
            self.oidc_authorization_endpoint = self.oidc_authorization_endpoint.strip() or f"{base}/auth"
            self.oidc_token_endpoint = self.oidc_token_endpoint.strip() or f"{base}/token"
            self.oidc_jwks_url = self.oidc_jwks_url.strip() or f"{base}/certs"
            self.oidc_redirect_uri = (
                self.oidc_redirect_uri.strip() or f"{self.public_base_url}/api/v1/auth/oidc/callback"
            )
        return self

    @model_validator(mode="after")
    def _resolve_git_sha(self) -> Settings:
        self.git_sha = (
            self.git_sha.strip()
            or os.environ.get("GIT_SHA", "").strip()
            or os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip()
        )
        return self

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
    def break_glass_set(self) -> frozenset[str]:
        emails = {e.strip().lower() for e in self.break_glass_emails.split(",") if e.strip()}
        return frozenset(emails | {self.bootstrap_admin_email.strip().lower()})

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

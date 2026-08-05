"""Fin-Content Engine — worker settings (Part II §4.9).

Two-tier config (§2.5):
  - THIS module: secrets + structural config, read from env (FCE_ prefix).
    Changed rarely; requires a redeploy.
  - The `config` DB table: tuning values (thresholds, cadences, caps).
    Read at job-fire time by `app.config`. Tunable without redeploy.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Env-driven settings. All have the FCE_ prefix (e.g. FCE_DATABASE_URL)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="FCE_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Supabase (worker uses service-role key; bypasses RLS) ---
    supabase_url: str = "http://localhost:54321"
    supabase_service_key: SecretStr = SecretStr("dev-only")

    # --- Postgres direct connection (used for pgvector queries + writes) ---
    database_url: str = "postgresql://postgres:postgres@localhost:5432/fce"

    # --- SEC EDGAR (mandatory UA per their fair-access policy; carries email) ---
    edgar_user_agent: str = "Fin-Content Engine fin-content@localhost (dev)"

    # --- Embedding edge function ---
    embedding_edge_function_url: str = "http://localhost:54321/functions/v1/embed"
    embedding_timeout_seconds: int = 5

    # --- Worker runtime ---
    scheduler_max_workers: int = 4
    log_level: str = "INFO"

    # --- YouTube Data API (Phase 4) ---
    youtube_token_path: Path = Path("token.json")
    youtube_channel_id: str = ""

    # --- Test/dev only ---
    # When true, `app.embed` returns a deterministic hash-derived vector instead
    # of calling the edge function. Used by conftest and `make test`.
    embed_mock: bool = False

    # Sentinel env var set by tests so they can short-circuit network calls.
    testing: bool = False


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Tests can override via `get_settings.cache_clear()`."""
    return Settings()

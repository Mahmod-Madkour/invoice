"""Settings from environment variables (spec §12; documented in .env.example)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fixed by the spec (§11), not configurable.
MAX_BODY_BYTES = 256 * 1024
RENDER_SLOT_TIMEOUT_SECONDS = 10.0
RATE_LIMIT_WINDOW_SECONDS = 60.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    port: int = Field(8000, ge=1, le=65535)  # read by the uvicorn command line, listed for completeness
    rows_per_table: int = Field(20, ge=1, le=30)
    tables_per_page: int = Field(2, ge=1, le=2)  # the page layout has two table slots
    max_items: int = Field(1000, ge=1)
    rate_limit_per_minute: int = Field(10, ge=1)
    max_concurrent_renders: int = Field(2, ge=1)
    enable_api_docs: bool = False
    app_password: SecretStr = SecretStr("")  # empty = Basic Auth disabled
    domain: str = "localhost"  # used by Caddy only
    log_level: Literal["critical", "error", "warning", "info", "debug"] = "info"

    @field_validator("log_level", mode="before")
    @classmethod
    def _lowercase_level(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value


@lru_cache
def get_settings() -> Settings:
    return Settings()

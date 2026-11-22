from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "prod"] = "dev"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:latest"
    # Opt in to a JSON schema. Off by default; prod always keeps it off.
    ollama_structured_output: bool = False
    # One hung call must not consume the whole suggestion, and the env cannot raise these.
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_attempt_timeout_seconds: float = Field(default=20, gt=0, le=20)
    # Budget covers at least two attempt timeouts so a slow first call can still retry.
    llm_suggest_budget_seconds: float = Field(default=40, gt=0, le=40)
    # Process-wide caps, split by mode. Nginx is the only prod caller.
    # LLM hard ceiling (spend safety net). Raised so Auto Play rarely hits it;
    # the real LLM throttle is llm_max_in_flight.
    suggest_rate_limit_requests: int = Field(default=60, ge=1, le=120)
    # Expectimax Auto Play ≈1 suggest/s (SETTLE_MS + AUTO_PLAY_GAP_MS). Design load:
    # 4 demo tabs → ~4×65/min × ~1.4 cushion = 360 / window. No LLM in-flight gate here.
    suggest_rate_limit_expectimax_requests: int = Field(default=360, ge=1, le=600)
    suggest_rate_limit_window_seconds: float = Field(default=60, ge=1, le=3600)
    # Concurrent LLM /suggest calls admitted to Ollama (capacity gate).
    llm_max_in_flight: int = Field(default=1, ge=1, le=8)
    # Process-wide cap on POST /client-events (ops metric integrity, not player auth).
    # Separate from the suggest LLM / expectimax buckets.
    client_events_rate_limit_requests: int = Field(default=60, ge=1, le=600)
    client_events_rate_limit_window_seconds: float = Field(default=60, ge=1, le=3600)
    # Host port the page is published on (Compose / local Vite). CORS allowlist
    # follows this so a worktree can move off 5173 without editing code.
    client_host_port: int = Field(default=5173, ge=1, le=65535)
    phoenix_collector_endpoint: str = "http://localhost:6006"
    phoenix_api_key: str | None = None
    # Dev and prod export. CI sets EXPORT_TRACES=false.
    export_traces: bool = True

    @model_validator(mode="after")
    def prod_uses_plain_json(self) -> "Settings":
        if self.app_env == "prod":
            self.ollama_structured_output = False
        return self

    @model_validator(mode="after")
    def budget_covers_two_attempts(self) -> "Settings":
        # Raise a stale short budget up to two attempt timeouts (upgrade-safe).
        needed = self.llm_attempt_timeout_seconds * 2
        if self.llm_suggest_budget_seconds < needed:
            self.llm_suggest_budget_seconds = needed
        return self

    @property
    def cors_origins(self) -> list[str]:
        port = self.client_host_port
        return [f"http://localhost:{port}", f"http://127.0.0.1:{port}"]

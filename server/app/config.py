from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["dev", "prod"] = "dev"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:latest"
    # Dev can opt into a JSON schema. Prod always parses plain JSON from the prompt.
    ollama_structured_output: bool = True
    # One hung call must not consume the whole suggestion, and the env cannot raise these.
    llm_max_attempts: int = Field(default=3, ge=1, le=5)
    llm_attempt_timeout_seconds: float = Field(default=10, gt=0, le=10)
    llm_suggest_budget_seconds: float = Field(default=20, gt=0, le=20)
    # The whole process, not each caller. Nginx is the only prod caller.
    suggest_rate_limit_requests: int = Field(default=5, ge=1, le=30)
    suggest_rate_limit_window_seconds: float = Field(default=60, ge=1, le=3600)
    phoenix_collector_endpoint: str = "http://localhost:6006"
    phoenix_api_key: str | None = None
    # Dev and prod export. CI sets EXPORT_TRACES=false.
    export_traces: bool = True

    @model_validator(mode="after")
    def prod_uses_plain_json(self) -> "Settings":
        if self.app_env == "prod":
            self.ollama_structured_output = False
        return self

from app.config import Settings


def isolated_settings(**overrides: object) -> Settings:
    """Settings from explicit values, so a developer .env cannot change the test."""
    values: dict[str, object] = {
        "app_env": "dev",
        "ollama_base_url": "http://ollama.test",
        "ollama_model": "test-model",
        "ollama_structured_output": True,
        "llm_max_attempts": 3,
    }
    values.update(overrides)
    return Settings(**values)

from app.config import Settings

# Right-hand column. Left only slides it, which is also the fallback direction.
COLUMN_PAIR = [
    [0, 0, 0, 4],
    [0, 0, 0, 4],
    [0, 0, 0, 8],
    [0, 0, 0, 0],
]

# Sorted top row, plus a 2 in the opposite corner. Up wrecks the row.
# Right only slides that 2, and up is the fallback.
SORTED_ROW = [
    [16, 8, 4, 2],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [2, 0, 0, 0],
]


def isolated_settings(**overrides: object) -> Settings:
    """Settings from explicit values, so a developer .env cannot change the test."""
    values: dict[str, object] = {
        "app_env": "dev",
        "ollama_base_url": "http://ollama.test",
        "ollama_model": "test-model",
        "ollama_structured_output": True,
        "llm_max_attempts": 3,
        "llm_attempt_timeout_seconds": 20,
        "llm_suggest_budget_seconds": 40,
    }
    values.update(overrides)
    return Settings(**values)

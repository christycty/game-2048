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

# test_suggest_e2e shares one app across every parametrized /suggest.
# Keep these equal to len(E2E_BOARDS) * len(E2E_RUN_IDS) in that file.
E2E_BOARD_COUNT = 2
E2E_RUN_COUNT = 3
E2E_SUGGEST_CALLS = E2E_BOARD_COUNT * E2E_RUN_COUNT
# Shared e2e suggest_client rate-limit budget. Intentionally loose above the
# parametrized matrix so adding another @pytest.mark.e2e LLM POST does not
# require a paired constant bump (extras today: traceparent + metrics).
# Settings caps suggest_rate_limit_requests at 30; stay under that.
E2E_RATE_LIMIT_REQUESTS = 24
assert E2E_RATE_LIMIT_REQUESTS > E2E_SUGGEST_CALLS

# Every Settings field must appear here. Init kwargs beat env; omitted fields
# still read SUGGEST_RATE_LIMIT_* / .env and the helper stops being isolated.
ISOLATED_SETTINGS_DEFAULTS: dict[str, object] = {
    "app_env": "dev",
    "ollama_base_url": "http://ollama.test",
    "ollama_model": "test-model",
    "ollama_structured_output": False,
    "llm_max_attempts": 3,
    "llm_attempt_timeout_seconds": 20,
    "llm_suggest_budget_seconds": 40,
    "suggest_rate_limit_requests": 5,
    "suggest_rate_limit_expectimax_requests": 30,
    "suggest_rate_limit_window_seconds": 60,
    "client_host_port": 5173,
    "phoenix_collector_endpoint": "http://phoenix.test",
    "phoenix_api_key": None,
    "export_traces": False,
}


def isolated_settings(**overrides: object) -> Settings:
    """Settings from explicit values, so a developer .env cannot change the test."""
    values = dict(ISOLATED_SETTINGS_DEFAULTS)
    values.update(overrides)
    return Settings(**values)

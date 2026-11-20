from app.config import Settings

# test_suggest_e2e shares one app across every parametrized /suggest.
# Keep these equal to len(E2E_BOARDS) * len(E2E_RUN_IDS) in that file.
E2E_BOARD_COUNT = 2
E2E_RUN_COUNT = 3
E2E_SUGGEST_CALLS = E2E_BOARD_COUNT * E2E_RUN_COUNT

# Every Settings field must appear here. Init kwargs beat env; omitted fields
# still read SUGGEST_RATE_LIMIT_* / .env and the helper stops being isolated.
ISOLATED_SETTINGS_DEFAULTS: dict[str, object] = {
    "app_env": "dev",
    "ollama_base_url": "http://ollama.test",
    "ollama_model": "test-model",
    "ollama_structured_output": True,
    "llm_max_attempts": 3,
    "llm_attempt_timeout_seconds": 10,
    "llm_suggest_budget_seconds": 20,
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

import pytest

from app.config import Settings
from helpers import ISOLATED_SETTINGS_DEFAULTS, isolated_settings
from test_load_expectimax import _CLIENT_GAME_JS, _autoplay_cycle_seconds


def test_isolated_settings_pins_every_settings_field() -> None:
    """New Settings fields must be added to ISOLATED_SETTINGS_DEFAULTS or env leaks in."""
    assert set(ISOLATED_SETTINGS_DEFAULTS) == set(Settings.model_fields)


def test_isolated_settings_ignores_hostile_rate_limit_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUGGEST_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("SUGGEST_RATE_LIMIT_EXPECTIMAX_REQUESTS", "1")
    monkeypatch.setenv("SUGGEST_RATE_LIMIT_WINDOW_SECONDS", "1")
    monkeypatch.setenv("LLM_MAX_IN_FLIGHT", "8")
    monkeypatch.setenv("CLIENT_EVENTS_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("CLIENT_EVENTS_RATE_LIMIT_WINDOW_SECONDS", "1")
    settings = isolated_settings()
    assert settings.suggest_rate_limit_requests == 60
    assert settings.suggest_rate_limit_expectimax_requests == 360
    assert settings.suggest_rate_limit_window_seconds == 60
    assert settings.llm_max_in_flight == 1
    assert settings.client_events_rate_limit_requests == 60
    assert settings.client_events_rate_limit_window_seconds == 60


def test_expectimax_load_client_cycle_parser_matches_game_js() -> None:
    """Catch client game.js moves or cadence formula drift in default PR CI."""
    assert _CLIENT_GAME_JS.is_file()
    assert _autoplay_cycle_seconds() == pytest.approx(0.91, abs=0.001)

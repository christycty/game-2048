import json
import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.llm import LlmError, ModelSuggestion, OllamaClient, _prompt, parse_move
from app.main import create_app
from app.rate_limit import SuggestRateLimiter
from app.schemas import MAX_TILE
from app.suggester import MoveSuggester
from helpers import (
    COLUMN_PAIR,
    E2E_BOARD_COUNT,
    E2E_RATE_LIMIT_REQUESTS,
    E2E_RUN_COUNT,
    E2E_SUGGEST_CALLS,
    SORTED_ROW,
    isolated_settings,
)

OPEN_BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

MERGE_BOARD = [
    [2, 2, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

STUCK_BOARD = [
    [2, 4, 8, 16],
    [32, 64, 128, 256],
    [512, 1024, 2048, 4096],
    [8192, 16384, 32768, 65536],
]


class FakeLLM:
    def __init__(self, replies: list) -> None:
        self._replies = list(replies)
        self.calls = 0

    def suggest_move(
        self,
        board: list[list[int]],
        *,
        legal: list[str],
        rejected: list[str],
        invalid_reply: bool,
        cancel=None,
    ) -> ModelSuggestion:
        self.calls += 1
        self.legal = legal
        self.rejected = list(rejected)
        self.invalid_reply = invalid_reply
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, str):
            return ModelSuggestion(reply, "ok")
        return reply


def _client(llm: FakeLLM, env: str = "dev") -> TestClient:
    app = create_app(isolated_settings(app_env=env, llm_max_attempts=3), llm)
    return TestClient(app)


def test_health() -> None:
    response = _client(FakeLLM([])).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _suggest(client: TestClient) -> httpx.Response:
    return client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})


def test_suggest_rate_limit_stops_before_the_model() -> None:
    llm = FakeLLM(["right", "right", "right"])
    clock = _Clock()
    limiter = SuggestRateLimiter(2, 60, clock)
    client = TestClient(
        create_app(
            isolated_settings(),
            llm,
            rate_limiters={"llm": limiter, "expectimax": SuggestRateLimiter(30, 60, clock)},
        )
    )
    assert _suggest(client).status_code == 200
    assert _suggest(client).status_code == 200

    blocked = _suggest(client)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "too many suggestions"
    assert blocked.headers["retry-after"] == "60"
    assert llm.calls == 2

    clock.now = 60
    assert _suggest(client).status_code == 200
    assert llm.calls == 3


def test_suggest_rate_limit_uses_settings() -> None:
    llm = FakeLLM(["right", "right"])
    settings = isolated_settings(
        suggest_rate_limit_requests=1,
        suggest_rate_limit_window_seconds=60,
    )
    client = TestClient(create_app(settings, llm))
    assert _suggest(client).status_code == 200
    blocked = _suggest(client)
    assert blocked.status_code == 429
    assert llm.calls == 1


def test_default_llm_rate_limit_blocks_the_sixth_call() -> None:
    """Defaults are part of the contract: one app allows 5 llm suggests, then 429.

    Opt-in e2e shares one module-scoped client across more posts than that.
    Suites that need more room must raise SUGGEST_RATE_LIMIT_REQUESTS.
    """
    from app.config import Settings

    # Field default, not Settings() — that still reads the process env / .env.
    assert Settings.model_fields["suggest_rate_limit_requests"].default == 5
    assert Settings.model_fields["suggest_rate_limit_expectimax_requests"].default == 30
    assert E2E_SUGGEST_CALLS == E2E_BOARD_COUNT * E2E_RUN_COUNT
    assert E2E_RATE_LIMIT_REQUESTS > E2E_SUGGEST_CALLS
    assert E2E_RATE_LIMIT_REQUESTS > 5

    llm = FakeLLM(["right"] * 6)
    client = TestClient(create_app(isolated_settings(), llm))
    for _ in range(5):
        assert _suggest(client).status_code == 200
    blocked = _suggest(client)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"]
    assert llm.calls == 5


def test_expectimax_rate_limit_is_separate_from_llm() -> None:
    """Expectimax has its own higher cap so Auto Play does not spend the LLM budget."""
    llm = FakeLLM(["right"] * 5)
    settings = isolated_settings(
        suggest_rate_limit_requests=1,
        suggest_rate_limit_expectimax_requests=3,
    )
    client = TestClient(create_app(settings, llm))
    assert _suggest(client).status_code == 200
    assert _suggest(client).status_code == 429
    assert llm.calls == 1

    for _ in range(3):
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"})
        assert response.status_code == 200
    blocked = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"})
    assert blocked.status_code == 429
    assert llm.calls == 1


def test_e2e_rate_limit_covers_shared_fixture_budget() -> None:
    """A shared app sized like the e2e fixture survives its rate-limit budget."""
    llm = FakeLLM(["right"] * E2E_RATE_LIMIT_REQUESTS)
    settings = isolated_settings(suggest_rate_limit_requests=E2E_RATE_LIMIT_REQUESTS)
    client = TestClient(create_app(settings, llm))
    for _ in range(E2E_RATE_LIMIT_REQUESTS):
        assert _suggest(client).status_code == 200
    assert llm.calls == E2E_RATE_LIMIT_REQUESTS


def test_health_stays_ok_when_ollama_is_down() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("health must not call ollama")

    client, http = _ollama_client(handler)
    try:
        response = client.get("/health")
    finally:
        http.close()
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173"])
def test_browser_origins_can_call_suggest(origin: str) -> None:
    response = _client(FakeLLM([])).options(
        "/suggest",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_other_origins_cannot_call_suggest() -> None:
    response = _client(FakeLLM([])).options(
        "/suggest",
        headers={
            "Origin": "http://192.168.1.5:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_cors_follows_client_host_port() -> None:
    app = create_app(isolated_settings(client_host_port=5180), FakeLLM([]))
    client = TestClient(app)
    allowed = client.options(
        "/suggest",
        headers={
            "Origin": "http://127.0.0.1:5180",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert allowed.headers["access-control-allow-origin"] == "http://127.0.0.1:5180"
    blocked = client.options(
        "/suggest",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert blocked.headers.get("access-control-allow-origin") is None


def test_docs_follow_environment() -> None:
    assert _client(FakeLLM([])).get("/docs").status_code == 200
    assert _client(FakeLLM([]), env="prod").get("/docs").status_code == 404
    assert _client(FakeLLM([]), env="prod").get("/openapi.json").status_code == 404


def test_llm_returns_legal_move() -> None:
    llm = FakeLLM(["left"])
    response = _client(llm).post("/suggest", json={"board": MERGE_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json() == {"move": "left", "mode": "llm", "source": "llm", "reason": "ok"}
    assert llm.calls == 1


def test_illegal_move_is_retried() -> None:
    llm = FakeLLM(["up", "down"])
    response = _client(llm).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json()["move"] == "down"
    assert response.json()["source"] == "llm"
    assert llm.calls == 2


def test_exhausted_retries_fall_back() -> None:
    llm = FakeLLM([LlmError("bad"), "up", "left"])
    response = _client(llm).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json() == {
        "move": "right",
        "mode": "llm",
        "source": "fallback",
        "reason": None,
    }
    assert llm.calls == 3


def test_expectimax_skips_the_model() -> None:
    llm = FakeLLM(["up"])
    response = _client(llm).post("/suggest", json={"board": SORTED_ROW, "mode": "expectimax"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "expectimax"
    assert body["source"] == "expectimax"
    # Up is the fallback and would smash the sorted row. Right only slides the 2.
    assert body["move"] == "right"
    assert body["reason"].startswith("Score of each direction: ")
    assert "Up = N/A" not in body["reason"]  # up is legal but worse
    assert "Left = N/A" in body["reason"]
    assert llm.calls == 0


def test_expectimax_merges_instead_of_sliding() -> None:
    response = _client(FakeLLM([])).post(
        "/suggest", json={"board": COLUMN_PAIR, "mode": "expectimax"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "expectimax"
    assert body["move"] in {"up", "down"}
    assert body["reason"].startswith("Score of each direction: ")
    assert "Left =" in body["reason"]
    assert "N/A" in body["reason"]


def test_expectimax_drops_an_illegal_search_move(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.expectimax import Choice

    monkeypatch.setattr(
        "app.suggester.choose_move",
        lambda _board, **_kwargs: Choice(
            "up", "Score of each direction: Left = N/A, Right = 1.0, Up = 2.0, Down = 1.0"
        ),
    )
    response = _client(FakeLLM([])).post(
        "/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "move": "right",
        "mode": "expectimax",
        "source": "fallback",
        "reason": None,
    }


def test_expectimax_falls_back_when_search_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    # Budget expired before any depth, or search aborted — not a scored move.
    monkeypatch.setattr("app.suggester.choose_move", lambda _board, **_kwargs: None)
    response = _client(FakeLLM([])).post(
        "/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "move": "right",
        "mode": "expectimax",
        "source": "fallback",
        "reason": None,
    }


def test_expectimax_stuck_board_is_conflict() -> None:
    response = _client(FakeLLM([])).post(
        "/suggest", json={"board": STUCK_BOARD, "mode": "expectimax"}
    )
    assert response.status_code == 409


def test_stuck_board_is_conflict() -> None:
    response = _client(FakeLLM(["left"])).post(
        "/suggest", json={"board": STUCK_BOARD, "mode": "llm"}
    )
    assert response.status_code == 409


def test_bad_payload_is_unprocessable() -> None:
    client = _client(FakeLLM([]))
    short = client.post("/suggest", json={"board": [[0, 0, 0, 0]], "mode": "llm"})
    unknown = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "random"})
    negative = client.post(
        "/suggest",
        json={"board": [[-2, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], "mode": "llm"},
    )
    huge = client.post(
        "/suggest",
        json={
            "board": [[MAX_TILE + 1, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 1]],
            "mode": "llm",
        },
    )
    assert short.status_code == 422
    assert unknown.status_code == 422
    assert negative.status_code == 422
    assert huge.status_code == 422


def test_prompt_names_legal_moves_and_a_rejected_one() -> None:
    text = _prompt(OPEN_BOARD, legal=["right", "down"], rejected=[], invalid_reply=False)
    assert "2 0 0 0\n0 0 0 0\n0 0 0 0\n0 0 0 0" in text
    assert "Legal moves: right, down." in text
    assert "Rejected moves:" not in text
    assert "could not be used" not in text
    assert '{"move":"...","reason":"..."}' in text
    assert "|" not in text
    assert "at most 50 words" in text
    assert "No markdown and no other text." in text

    retried = _prompt(OPEN_BOARD, legal=["right", "down"], rejected=["up"], invalid_reply=True)
    assert "Rejected moves: up." in retried
    assert "The previous reply could not be used." in retried


def test_llm_returns_the_model_reason() -> None:
    reason = "The two tiles in the top row merge."
    llm = FakeLLM([ModelSuggestion("left", reason)])
    response = _client(llm).post("/suggest", json={"board": MERGE_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json()["move"] == "left"
    assert response.json()["source"] == "llm"
    assert response.json()["reason"] == reason


def test_ollama_client_omits_schema_when_structured_output_is_off() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "format" not in body
        return httpx.Response(
            200,
            json={"message": {"content": '{"move": "right", "reason": "Slides the tile."}'}},
        )

    transport = httpx.MockTransport(handler)
    settings = isolated_settings(ollama_structured_output=False)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        suggestion = OllamaClient(settings, client=http).suggest_move(
            OPEN_BOARD,
            legal=["right", "down"],
            rejected=[],
            invalid_reply=False,
        )
    assert suggestion == ModelSuggestion("right", "Slides the tile.")


def test_ollama_client_parses_structured_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["format"]["properties"]["move"]["enum"] == ["right", "down"]
        assert body["format"]["required"] == ["move", "reason"]
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={"message": {"content": '{"move": "left", "reason": "Merges the pair."}'}},
        )

    transport = httpx.MockTransport(handler)
    settings = isolated_settings(ollama_structured_output=True)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        suggestion = OllamaClient(settings, client=http).suggest_move(
            OPEN_BOARD,
            legal=["right", "down"],
            rejected=[],
            invalid_reply=False,
        )
    assert suggestion == ModelSuggestion("left", "Merges the pair.")


def test_move_without_a_reason_falls_back() -> None:
    llm = FakeLLM([ModelSuggestion("left", None)] * 3)
    response = _client(llm).post("/suggest", json={"board": MERGE_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json()["source"] == "fallback"
    assert response.json()["reason"] is None
    assert llm.calls == 3


def test_ollama_client_rejects_a_blank_reason() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        body = {"message": {"content": '{"move": "left", "reason": "  "}'}}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        with pytest.raises(LlmError):
            OllamaClient(isolated_settings(), client=http).suggest_move(
                OPEN_BOARD,
                legal=["right", "down"],
                rejected=[],
                invalid_reply=False,
            )


def test_ollama_client_rejects_a_missing_reason() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": '{"move": "left"}'}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        with pytest.raises(LlmError):
            OllamaClient(isolated_settings(), client=http).suggest_move(
                OPEN_BOARD,
                legal=["right", "down"],
                rejected=[],
                invalid_reply=False,
            )


def test_reason_is_cut_to_fifty_words() -> None:
    words = " ".join(f"w{i}" for i in range(60))
    suggestion = parse_move({"move": "left", "reason": words})
    assert suggestion.move == "left"
    assert suggestion.reason is not None
    assert len(suggestion.reason.split()) == 50


def test_reason_is_cut_when_one_token_is_huge() -> None:
    suggestion = parse_move({"move": "left", "reason": "x" * 800})
    assert suggestion.reason is not None
    assert len(suggestion.reason) == 400


def _ollama_client(handler) -> tuple[TestClient, httpx.Client]:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://ollama.test")
    settings = isolated_settings(llm_max_attempts=2, ollama_structured_output=False)
    app = create_app(settings, OllamaClient(settings, client=http))
    return TestClient(app), http


def test_suggest_falls_back_when_ollama_http_fails() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "unavailable"})

    client, http = _ollama_client(handler)
    try:
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    finally:
        http.close()
    assert response.status_code == 200
    assert response.json() == {
        "move": "right",
        "mode": "llm",
        "source": "fallback",
        "reason": None,
    }


def test_suggest_falls_back_when_message_is_null() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": None})

    client, http = _ollama_client(handler)
    try:
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    finally:
        http.close()
    assert response.status_code == 200
    assert response.json()["source"] == "fallback"
    assert response.json()["move"] == "right"


def test_ollama_client_rejects_unusable_output() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not-json"}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        with pytest.raises(LlmError):
            OllamaClient(isolated_settings(), client=http).suggest_move(
                OPEN_BOARD,
                legal=["right", "down"],
                rejected=[],
                invalid_reply=False,
            )


def test_rejected_move_is_included_in_the_next_prompt() -> None:
    prompts: list[str] = []
    replies = [
        {"message": {"content": '{"move": "up", "reason": "Hold the corner."}'}},
        {"message": {"content": '{"move": "down", "reason": "Open the column."}'}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        prompts.append(json.loads(request.content)["messages"][0]["content"])
        return httpx.Response(200, json=replies.pop(0))

    client, http = _ollama_client(handler)
    try:
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    finally:
        http.close()
    assert response.status_code == 200
    assert response.json()["move"] == "down"
    assert response.json()["source"] == "llm"
    assert "Legal moves: right, down." in prompts[0]
    assert "Rejected moves:" not in prompts[0]
    assert "Rejected moves: up." in prompts[1]
    assert "Legal moves: right, down." in prompts[1]


def test_unusable_reply_is_described_on_the_next_prompt() -> None:
    prompts: list[str] = []
    replies = [
        {"message": {"content": "not-json"}},
        {"message": {"content": '{"move": "down", "reason": "Open the column."}'}},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "format" not in body
        prompts.append(body["messages"][0]["content"])
        return httpx.Response(200, json=replies.pop(0))

    client, http = _ollama_client(handler)
    try:
        response = client.post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    finally:
        http.close()
    assert response.json()["source"] == "llm"
    assert "could not be used" not in prompts[0]
    assert "The previous reply could not be used." in prompts[1]


def test_prod_omits_the_json_schema_even_when_the_flag_is_on() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"message": {"content": '{"move": "down", "reason": "Slide the tile."}'}},
        )

    settings = isolated_settings(app_env="prod", ollama_structured_output=True)
    assert settings.ollama_structured_output is False
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        app = create_app(settings, OllamaClient(settings, client=http))
        response = TestClient(app).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert "format" not in seen


def test_attempt_count_stays_between_one_and_five() -> None:
    with pytest.raises(ValidationError):
        isolated_settings(llm_max_attempts=0)
    with pytest.raises(ValidationError):
        isolated_settings(llm_max_attempts=6)
    with pytest.raises(ValidationError):
        isolated_settings(llm_attempt_timeout_seconds=30)
    with pytest.raises(ValidationError):
        isolated_settings(llm_suggest_budget_seconds=60)
    # 20s attempts need a 40s budget. A stale shorter budget is raised to the floor.
    raised = isolated_settings(llm_attempt_timeout_seconds=20, llm_suggest_budget_seconds=30)
    assert raised.llm_suggest_budget_seconds == 40
    shorter = isolated_settings(llm_attempt_timeout_seconds=10, llm_suggest_budget_seconds=20)
    assert shorter.llm_attempt_timeout_seconds == 10
    assert shorter.llm_suggest_budget_seconds == 20


def test_fallback_logs_the_failed_attempts(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="app.suggester")
    llm = FakeLLM([LlmError("ollama request failed")] * 3)
    response = _client(llm).post("/suggest", json={"board": OPEN_BOARD, "mode": "llm"})
    assert response.json()["source"] == "fallback"
    assert "fell back to right" in caplog.text
    assert "ollama request failed" in caplog.text


def test_time_budget_stops_further_attempts() -> None:
    llm = FakeLLM([LlmError("slow")] * 3)
    # After the first attempt, only 15s remain — below the 20s attempt timeout.
    ticks = iter([0.0, 0.0, 25.0])
    suggester = MoveSuggester(
        llm,
        max_attempts=3,
        budget_seconds=40,
        attempt_timeout_seconds=20,
        clock=lambda: next(ticks),
    )
    response = suggester.suggest(OPEN_BOARD, "llm")
    assert response.source == "fallback"
    assert llm.calls == 1


def test_lifespan_closes_the_owned_client(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[int] = []
    real_close = OllamaClient.close

    def spy_close(self: OllamaClient) -> None:
        closed.append(1)
        real_close(self)

    monkeypatch.setattr(OllamaClient, "close", spy_close)
    app = create_app(isolated_settings())
    with TestClient(app):
        assert closed == []
    assert closed == [1]


def test_lifespan_leaves_an_injected_client_open() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": []})

    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://ollama.test")
    settings = isolated_settings()
    app = create_app(settings, OllamaClient(settings, client=http))
    with TestClient(app):
        pass
    response = http.get("/api/tags")
    assert response.status_code == 200
    http.close()

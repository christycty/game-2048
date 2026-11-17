import json

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LlmError, OllamaClient
from app.main import create_app

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

    def suggest_move(self, board: list[list[int]]) -> str:
        self.calls += 1
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _client(llm: FakeLLM, env: str = "dev") -> TestClient:
    app = create_app(Settings(app_env=env, llm_max_attempts=3), llm)
    return TestClient(app)


def test_health() -> None:
    response = _client(FakeLLM([])).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_docs_follow_environment() -> None:
    assert _client(FakeLLM([])).get("/docs").status_code == 200
    assert _client(FakeLLM([]), env="prod").get("/docs").status_code == 404
    assert _client(FakeLLM([]), env="prod").get("/openapi.json").status_code == 404


def test_llm_returns_legal_move() -> None:
    llm = FakeLLM(["left"])
    response = _client(llm).post("/suggest", json={"board": MERGE_BOARD, "mode": "llm"})
    assert response.status_code == 200
    assert response.json() == {"move": "left", "mode": "llm", "source": "llm"}
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
    assert response.json() == {"move": "right", "mode": "llm", "source": "fallback"}
    assert llm.calls == 3


def test_expectimax_stub_skips_the_model() -> None:
    llm = FakeLLM(["up"])
    response = _client(llm).post("/suggest", json={"board": OPEN_BOARD, "mode": "expectimax"})
    assert response.status_code == 200
    assert response.json() == {
        "move": "right",
        "mode": "expectimax",
        "source": "expectimax-stub",
    }
    assert llm.calls == 0


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
    assert short.status_code == 422
    assert unknown.status_code == 422
    assert negative.status_code == 422


def test_ollama_client_parses_structured_output() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["format"]["required"] == ["move"]
        assert body["stream"] is False
        return httpx.Response(200, json={"message": {"content": '{"move": "left"}'}})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="http://ollama.test") as http:
        move = OllamaClient(Settings(), client=http).suggest_move(OPEN_BOARD)
    assert move == "left"


def _ollama_client(handler) -> tuple[TestClient, httpx.Client]:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="http://ollama.test")
    app = create_app(Settings(llm_max_attempts=2), OllamaClient(Settings(), client=http))
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
    assert response.json() == {"move": "right", "mode": "llm", "source": "fallback"}


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
        try:
            OllamaClient(Settings(), client=http).suggest_move(OPEN_BOARD)
        except LlmError:
            return
    raise AssertionError("expected LlmError")

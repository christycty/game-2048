import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.moves import legal_moves
from helpers import isolated_settings

MERGE_BOARD = [
    [2, 2, 4, 8],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]

CORNER_BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]


def _unavailable(base_url: str, model: str) -> str | None:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=2)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        return f"Ollama is not reachable at {base_url}: {exc}"
    names = [item.get("name", "") for item in response.json().get("models", [])]
    if model not in names:
        return f"{model} is not installed in Ollama"
    return None


@pytest.fixture(scope="module")
def suggest_client() -> TestClient:
    model = os.environ.get("OLLAMA_MODEL", "gemma4:latest")
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    reason = _unavailable(base_url, model)
    if reason:
        pytest.skip(reason)
    settings = isolated_settings(
        app_env="prod",
        ollama_model=model,
        ollama_base_url=base_url,
        llm_max_attempts=3,
    )
    # Prod parses the prompt's JSON. The schema format stays off.
    assert settings.ollama_structured_output is False
    return TestClient(create_app(settings))


@pytest.mark.e2e
@pytest.mark.parametrize("board", [MERGE_BOARD, CORNER_BOARD], ids=["merge", "corner"])
@pytest.mark.parametrize("run", [1, 2, 3])
def test_gemma_returns_a_legal_move_and_a_short_reason(
    suggest_client: TestClient,
    board: list[list[int]],
    run: int,
) -> None:
    response = suggest_client.post("/suggest", json={"board": board, "mode": "llm"})
    assert response.status_code == 200, f"run {run}"
    body = response.json()
    assert body["mode"] == "llm"
    assert body["source"] == "llm"
    assert body["move"] in legal_moves(board)
    words = body["reason"].split()
    assert 1 <= len(words) <= 50

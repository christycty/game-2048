# Server

FastAPI service that suggests the next 2048 move. The process is healthy even when Ollama is down. An LLM failure still returns a legal move from a fixed order. Expectimax is a stub that returns that same order without calling the model.

Agent/implementer detail for the API. Human architecture overview: [../architecture.md](../architecture.md). Product rules: [prd.md](prd.md).

## Run

From `server/`:

```bash
# copy server/.env.example if you want local overrides
uv sync --extra dev          # or: pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pytest                       # unit tests; skips e2e
pytest --e2e                 # needs a local Ollama and the configured model
ruff format --check . && ruff check .
```

Package name: `game-2048-server`. Entry: `app.main:app`. Python ≥ 3.11 (images use 3.12). See [runtime.md](runtime.md) for Compose, Docker, and env names shared with the host Ollama.

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, CORS, `/health`, `/suggest`. |
| `app/schemas.py` | Request and response models. Tile and mode validation. |
| `app/suggester.py` | Mode dispatch, LLM retries, fallback, expectimax stub. |
| `app/moves.py` | Slide/merge rules for legal moves and the fallback order. |
| `app/llm.py` | Ollama chat client, prompt, JSON parse. |
| `app/config.py` | Env-backed settings. |

## HTTP

| Method | Path | Success | Notes |
|---|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` | Never calls Ollama. |
| `POST` | `/suggest` | `SuggestResponse` | `409` when the board has no legal move. `422` on bad payload. |

CORS allows `http://localhost:5173` and `http://127.0.0.1:5173`, methods `GET` and `POST`. Other page origins cannot call the API from a browser.

In `APP_ENV=dev`, `/docs` and `/openapi.json` are open. In `prod` they return 404. Redoc is always off. Title: `2048 suggestions`.

### Request

```json
{
  "board": [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 2]],
  "mode": "llm"
}
```

`board` is exactly 4×4. Each cell is an int from `0` through `MAX_TILE` (`1 << 17`). `mode` is `llm` or `expectimax`.

### Response

```json
{
  "move": "right",
  "mode": "llm",
  "source": "llm",
  "reason": "Opens space on the left."
}
```

| Field | Values |
|---|---|
| `move` | `up`, `down`, `left`, `right` |
| `mode` | Echo of the request mode |
| `source` | `llm`, `fallback`, or `expectimax-stub` |
| `reason` | Non-empty string for `source: "llm"`. Otherwise `null`. |

## Suggestion pipeline

`MoveSuggester.suggest`:

1. Builds the legal move set with the same slide rules as the client.
2. Picks a fallback: first direction in `FALLBACK_ORDER` (`left`, `up`, `right`, `down`) that is legal. None → `NoLegalMove` → HTTP 409.
3. **`expectimax`**: returns that fallback immediately with `source: "expectimax-stub"` and no LLM call.
4. **`llm`**: up to `LLM_MAX_ATTEMPTS` calls, stopped early when the remaining `LLM_SUGGEST_BUDGET_SECONDS` cannot cover another `LLM_ATTEMPT_TIMEOUT_SECONDS` wait.
5. Accepts a reply only when the move is legal and the reason is a non-blank string after strip.
6. Retries on illegal moves (recorded as rejected), blank reasons, and `LlmError`.
7. After exhaustion: `source: "fallback"`, `move` is the fallback, `reason` is null.

## LLM (`OllamaClient`)

`POST {OLLAMA_BASE_URL}/api/chat` with `OLLAMA_MODEL`, non-streaming. The prompt lists the board, legal moves, any rejected moves, and asks for JSON `{"move":"...","reason":"..."}` only.

When `OLLAMA_STRUCTURED_OUTPUT` is true and `APP_ENV` is not `prod`, the request also sends a JSON schema that constrains `move` to the legal set. Prod always omits that schema so the model must follow the prompt text alone.

`parse_move` requires JSON with a known direction and a non-blank reason, then trims the reason to at most 50 words and 400 characters.

## Settings

Loaded from the environment and optional `server/.env` (Compose does not use that file for containers; see [runtime.md](runtime.md)).

| Setting | Default | Bounds / notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` or `prod` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Host process default |
| `OLLAMA_MODEL` | `gemma4:latest` | |
| `OLLAMA_STRUCTURED_OUTPUT` | `true` | Forced off in prod |
| `LLM_MAX_ATTEMPTS` | `3` | 1–5 |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | `10` | >0, ≤10 |
| `LLM_SUGGEST_BUDGET_SECONDS` | `20` | >0, ≤20 |

## Tests

- `tests/test_suggest.py` covers health, CORS, LLM success and reason, illegal-move retry, exhausted fallback, expectimax stub, stuck-board 409, bad payload 422, Ollama HTTP failures, prod schema omission, attempt bounds, and the time budget stop.
- `tests/test_moves.py` covers the slide and merge rules used for legality.
- `tests/test_suggest_e2e.py` is marked `e2e`. It talks to a real Ollama under `APP_ENV=prod` and asserts `source == "llm"` with a short reason.

## Not built yet

Expectimax is not a search. There is no rate limit, auth, or per-player quota. OpenTelemetry is not wired. The API does not persist games.

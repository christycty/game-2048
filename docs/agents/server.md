# Server

FastAPI service that suggests the next 2048 move. The process is healthy even when Ollama is down. On LLM exhaustion or an expectimax search miss the API still returns HTTP 200 with `source: "fallback"` and a legal move from a fixed order; the client treats fallback as an unusable suggestion (no **Play**—same as other failures). Expectimax runs a depth-limited search and does not call the model.

Agent/implementer detail for the API. Human architecture overview: [../architecture.md](../architecture.md). Product rules: [prd.md](prd.md).

## Run

From `server/`:

```bash
# copy server/.env.example if you want local overrides
uv sync --extra dev          # or: pip install -e ".[dev]"
uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_HOST_PORT:-8000}"
pytest                       # unit/API/concurrency; skips e2e + load
pytest --e2e                 # needs a local Ollama and the configured model
pytest --load -m load        # opt-in FakeLLM soak (not required PR CI)
ruff format --check . && ruff check .
```

Package name: `game-2048-server`. Entry: `app.main:app`. Python ≥ 3.11 (images use 3.12). See [runtime.md](runtime.md) for Compose, Docker, and env names shared with the host Ollama.

## Layout

| Path | Role |
|---|---|
| `app/main.py` | App factory, CORS, hard-ceiling + LLM in-flight gates, disconnect-cancel middleware, `/health`, `/suggest` (async), `/metrics`. |
| `app/schemas.py` | Request and response models. Tile and mode validation. |
| `app/suggester.py` | Mode dispatch, LLM retries, fallback, expectimax search; honors per-request cancel. |
| `app/expectimax.py` | Depth-limited expectimax with spawn chance nodes; checks cancel between depths and inside chance/max nodes. |
| `app/moves.py` | Slide/merge rules for legal moves and the fallback order. |
| `app/llm.py` | Ollama chat client, prompt, JSON parse; per-attempt `AsyncClient` with `task.cancel()` on disconnect (sync MockTransport path for tests). |
| `app/cancel.py` | `SuggestCancelled` — per-request stop (not process-wide). |
| `app/rate_limit.py` | Per-mode sliding-window hard ceiling (`SuggestRateLimiter.release` refunds after cancel) + `LlmInFlightGate` token-tracked capacity gate for LLM. |
| `app/config.py` | Env-backed settings. |
| `app/telemetry.py` | Phoenix OTLP traces + Prometheus `/metrics` (GenAI histograms + request_count). |

## HTTP

| Method | Path | Success | Notes |
|---|---|---|---|
| `GET` | `/health` | `{"status":"ok"}` | Never calls Ollama. |
| `GET` | `/metrics` | Prometheus text | Always on. GenAI + FastAPI HTTP series; inventory in [telemetry.md](telemetry.md). Not traced. |
| `POST` | `/suggest` | `SuggestResponse` | Handler order: Pydantic `422` (before either gate; does not consume caps) → that mode’s hard-ceiling sliding window `429` + `Retry-After` + `detail: "too many suggestions"` → **LLM only:** in-flight capacity acquire `429` + `Retry-After` (refunds the hard-ceiling hit if capacity is full) → suggester → `409` when no legal move → `200` with `SuggestResponse`. `499` when the client disconnects / cancels mid-run (best-effort if already gone); that request’s hard-ceiling token is released and its in-flight slot is freed in `finally`. |

Concurrent clients share one process (FastAPI threadpool + process-wide rate limiters + LLM in-flight gate). Cancel is **per request**: `DisconnectCancelMiddleware` tees ASGI receive for `/suggest` and sets that request’s `threading.Event` on `http.disconnect`. Each Ollama attempt uses its own `httpx.AsyncClient`; cancel cancels that attempt’s asyncio task so a blocked `post` unblocks without touching sibling suggests.

CORS allows `http://localhost:${CLIENT_HOST_PORT}` and `http://127.0.0.1:${CLIENT_HOST_PORT}` (default 5173), methods `GET` and `POST`. Same-origin `/suggest` through Vite or nginx does not need CORS; the allowlist remains for builds that set `VITE_API_BASE_URL` to the API origin.

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
| `source` | `llm`, `fallback`, or `expectimax` |
| `reason` | Non-empty for `source: "llm"` (model text) and `source: "expectimax"` (score line). `null` for `fallback`. |

Expectimax reason shape (illegal directions are `N/A`):

```text
Score of each direction: Left = N/A, Right = 1053.4, Up = N/A, Down = 771.2
```

## Suggestion pipeline

`MoveSuggester.suggest`:

1. Builds the legal move set with the same slide rules as the client.
2. Picks a fallback: first direction in `FALLBACK_ORDER` (`left`, `up`, `right`, `down`) that is legal. None → `NoLegalMove` → HTTP 409.
3. **`expectimax`**: `choose_move` runs depth-limited expectimax (chance node: uniform empty cell, 2 at 90% / 4 at 10%). Returns `source: "expectimax"` with the score-line `reason`. If search returns a non-legal move, or returns nothing (budget expired or an unreachable state before any depth finished), substitutes the fallback with `source: "fallback"`. A cut mid-depth keeps the last finished depth.
4. **`llm`**: up to `LLM_MAX_ATTEMPTS` calls, stopped early when the remaining `LLM_SUGGEST_BUDGET_SECONDS` cannot cover another `LLM_ATTEMPT_TIMEOUT_SECONDS` wait.
5. Accepts a reply only when the move is legal and the reason is a non-blank string after strip.
6. Retries on illegal moves (recorded as rejected), blank reasons, and `LlmError`.
7. After exhaustion: `source: "fallback"`, `move` is the fallback, `reason` is null.

Expectimax depth: open boards (≥8 empties) search to depth 1; tighter boards to depth 2. Wall budget ~0.5s with iterative deepening (keeps the last finished depth; if none finished, falls back). `N/A` in the reason means that direction is illegal, not unscored.

## LLM (`OllamaClient`)

`POST {OLLAMA_BASE_URL}/api/chat` with `OLLAMA_MODEL`, non-streaming. The prompt lists the board, legal moves, any rejected moves, and asks for JSON `{"move":"...","reason":"..."}` only.

`OLLAMA_STRUCTURED_OUTPUT` is off by default. When opted in and `APP_ENV` is not `prod`, the request also sends a JSON schema that constrains `move` to the legal set. Prod always omits that schema so the model must follow the prompt text alone.

`parse_move` requires JSON with a known direction and a non-blank reason, then trims the reason to at most 50 words and 400 characters.

## Settings

Loaded from the environment and optional `server/.env` (Compose does not use that file for containers; see [runtime.md](runtime.md)).

| Setting | Default | Bounds / notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` or `prod` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Host process default |
| `OLLAMA_MODEL` | `gemma4:latest` | |
| `OLLAMA_STRUCTURED_OUTPUT` | `false` | Opt in; forced off in prod |
| `LLM_MAX_ATTEMPTS` | `3` | 1–5 |
| `LLM_ATTEMPT_TIMEOUT_SECONDS` | `20` | >0, ≤20 |
| `LLM_SUGGEST_BUDGET_SECONDS` | `40` | >0, ≤40; raised to 2× attempt timeout when lower |
| `SUGGEST_RATE_LIMIT_REQUESTS` | `60` | 1–120; LLM hard ceiling (spend safety net) |
| `SUGGEST_RATE_LIMIT_EXPECTIMAX_REQUESTS` | `30` | 1–120; Expectimax bucket (process-wide) |
| `SUGGEST_RATE_LIMIT_WINDOW_SECONDS` | `60` | 1–3600; shared window for both modes |
| `LLM_MAX_IN_FLIGHT` | `1` | 1–8; concurrent LLM suggests admitted to Ollama |
| `CLIENT_HOST_PORT` | `5173` | 1–65535; CORS allowlist |
| `EXPORT_TRACES` | `true` | Gates **OTLP export** only (instrumentation still loads when `false`). Host uvicorn / one-off image runs honor this env; CI pytest and smoke `docker run` set `false`. Compose `dev`/`prod` hardcode `true` (see [runtime.md](runtime.md)). Metrics / `GET /metrics` stay on regardless. |
| `PHOENIX_COLLECTOR_ENDPOINT` | `http://localhost:6006` | Host process default; exporter posts to `{endpoint}/v1/traces` (or a full traces URL). Compose uses `COMPOSE_PHOENIX_COLLECTOR_ENDPOINT`. |
| `PHOENIX_API_KEY` | unset | Optional bearer; sent only for HTTPS or local/`host.docker.internal` HTTP |

## Observability

Phoenix = forensics (spans, prompts, retries, TTFT events). Grafana = ops aggregates from Prometheus scrapes of `GET /metrics`. Prometheus stores the time series; Grafana only queries them. Full inventory (every span, event, series, label, and Phoenix vs Grafana ownership): [telemetry.md](telemetry.md). Compose scrape UI: [runtime.md](runtime.md).

Typical LLM tree: FastAPI `POST /suggest` → `suggest` chain → sibling `ollama chat` spans per attempt. Expectimax opens `suggest` without LLM children. Stuck board (`409`) is a single HTTP span (no nested `suggest`). Auto HTTP spans skip `/health`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`. Retry/fallback detail may appear as span-only `failures` output (not in the API body).

## Tests

Shared Fake/Blocking LLM doubles live in `tests/helpers.py` (used by suggest, cancel, contract, and load).

- `tests/test_helpers.py` asserts `isolated_settings` pins every `Settings` field and ignores hostile `SUGGEST_RATE_LIMIT_*` env.
- `tests/test_suggest.py` covers health, CORS, per-mode hard ceilings before the suggester (including the **default** 60-call LLM hard ceiling and a separate Expectimax bucket), LLM in-flight capacity (`max_in_flight=1` and `=2`; capacity reject does not burn the hard ceiling; expectimax unaffected; slot free after drain), LLM success and reason, illegal-move retry, exhausted fallback, expectimax search + score reason, illegal-search fallback, stuck-board 409, bad payload 422, Ollama HTTP failures, prod schema omission, attempt bounds, and the time budget stop.
- `tests/test_suggest_http_contract.py` locks hard-ceiling vs capacity `429` (`Retry-After` window vs `1`; same `detail` until multi-client splits it), a combined scenario that surfaces **both** in one run, and cancel `499`.
- `tests/test_cancel.py` covers per-request cancel through suggester / expectimax (pre-set and mid-search via `_check`) / Ollama client (pre-set, mid-flight hanging POST with `task.cancel`, and single-POST when the caller already has a running loop), concurrent isolation (cancel A, B still completes; LLM isolation raises `LLM_MAX_IN_FLIGHT`), endpoint `499` mapping, disconnect middleware, concurrent ASGI disconnect cancelling A while B completes (LLM and expectimax) **and mid-flight occupancy** (after A’s 499 with `max_in_flight=2`, a third `/suggest` admits while B holds and a fourth is capacity-429), rate-limit token refund and in-flight slot release after cancel, and concurrent release not popping a sibling’s hit.
- `tests/test_load_suggest.py` is marked `load` (opt-in FakeLLM soak): N workers × M suggests at `LLM_MAX_IN_FLIGHT` 1 then 2; mixed hard-ceiling + capacity `429` classified by `Retry-After`; plus ASGI disconnect-under-capacity waves (`cancels` + `completes` account); asserts accounting and no slot leak after drain.
- `tests/test_expectimax.py` covers legality, spawn odds, depth/budget cutoffs, and the reason format.
- `tests/test_moves.py` covers the slide and merge rules used for legality.
- `tests/test_telemetry.py` covers Phoenix URL/header rules, per-app exporters, excluded `/health` and `/metrics`, span nesting, retries, errors, stuck-board span shape, GenAI series on `/metrics` after a suggest (success / request / response / parse / illegal_move / timeout + suggest sources), and HTTP scrape status codes for `/suggest` (200 / 422 / 409 / 429).
- `tests/test_suggest_e2e.py` is marked `e2e` for real Ollama under `APP_ENV=prod`. It sizes `SUGGEST_RATE_LIMIT_REQUESTS` from its parametrized call volume, asserts `source == "llm"` with a short reason, and includes a non-e2e expectimax HTTP smoke that does not need Ollama.

## Verification checklist

Run from `server/` after `pip install -e ".[dev]"` (or `uv sync --extra dev`). Goal: conclude the suggest path is solid **without reading implementation files**.

| Layer | Command | Pass if |
|---|---|---|
| Unit + API + concurrency + contract | `pytest` | All green; e2e and load skipped |
| Light chaos (disconnect mid-flight) | (included in default `pytest` via `test_cancel.py`) | Cancel A leaves B; while B holds at `max_in_flight=2`, third admits / fourth capacity-429; slot + hard-ceiling token refunded |
| Image smokes (all HTTP surfaces, no Ollama) | CI docker job: `APP_ENV=prod` API + client, then `bash scripts/smoke_api_images.sh` | `/health` ok; `/docs` + `/openapi.json` 404; expectimax via nginx `:5173/suggest`; `GET /metrics` has `suggest_source=expectimax` + `/suggest` 200; nginx does **not** proxy `/health` or `/metrics` |
| E2E (real Ollama) | `pytest --e2e` | Local Ollama up with `OLLAMA_MODEL`; asserts `source == "llm"` |
| Load / soak (FakeLLM + cancel waves) | `pytest --load -m load` | Workers join; accounting closes (incl. cancels + mixed `429` layers); final suggest / gate probe OK. Also: Actions → **Run workflow** (`workflow_dispatch` `load` job) |

**`429` layers (today):** same `detail: "too many suggestions"`. Distinguish by `Retry-After`: capacity ≈ `1`; hard ceiling ≈ remaining window seconds (often `60` when just filled). Covered in default CI (`test_suggest_http_contract`) and opt-in load. Distinct detail/labels land in the multi-client PR.

**Optional Grafana / Phoenix spot-checks** (when series exist — cancel-obs / multi-client may add panels): after a local Compose `--profile metrics` drill, confirm `/suggest` status rates and GenAI success/error lines move; Phoenix shows a `suggest` chain for a live LLM call. Not required to trust FakeLLM CI.

## Not built yet

There is no auth or per-player quota (the suggestion cap is process-wide). The API does not persist games. Expectimax depth stays shallow for latency, not tournament strength.

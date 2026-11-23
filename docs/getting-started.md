# Getting started

Two ways to run: local processes (typical while hacking) or Compose profiles.

## Prerequisites

- Node.js + npm (client)
- Python ≥ 3.11 with [uv](https://github.com/astral-sh/uv) or pip (server)
- [Ollama](https://ollama.com) on the host, with `OLLAMA_MODEL` (default `gemma4:latest`) (optional — needed only for LLM mode; Expectimax works without it)
- Docker (optional, for Compose)

## Path A — local processes

```bash
# 1. API — export API_HOST_PORT in shell if default port 8000 is taken (uvicorn ignores root .env)
cd server && uv sync --extra dev && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_HOST_PORT:-8000}"

# 2. Client — Vite reads repo-root .env if you override CLIENT_HOST_PORT / API_HOST_PORT
cd client && npm install && npm run dev

# 3. Optional (LLM mode only): Ollama listening on http://localhost:11434
```

Open `http://127.0.0.1:${CLIENT_HOST_PORT:-5173}` (copy `.env.example` to `.env` if default ports are taken; see [agents/runtime.md](agents/runtime.md) for multi-checkout port overrides and `server/.env`). By default the page calls same-origin `/suggest` via Vite's proxy; set `VITE_API_BASE_URL` only to call the API directly (CORS applies).

## Path B — Compose

```bash
cp .env.example .env   # optional; override ports if defaults are taken (see agents/runtime.md)
docker compose --profile dev up    # API + Vite
# or
docker compose --profile prod up   # nginx client; API unpublished
# optional scrapers:
docker compose --profile dev --profile metrics up
```

`docker compose up` with no profile starts nothing. Published ports are loopback-only (`API_HOST_PORT` 8000, `CLIENT_HOST_PORT` 5173; with `metrics`, `PROMETHEUS_HOST_PORT` / `GRAFANA_HOST_PORT`). Prod publishes only the client; nginx forwards `/suggest` and `/client-events`.

### Full ops walkthrough (optional)

- **Expectimax / board only** — no Ollama required.
- **LLM suggest** — host Ollama + model from `OLLAMA_MODEL` (first pull can take a while).
- **Grafana aggregates** — Compose `--profile metrics` as above.
- **Phoenix traces** — run Phoenix (or another OTLP collector) on the host; not a Compose service. API export defaults on via `EXPORT_TRACES` (see [agents/runtime.md](agents/runtime.md) / [agents/telemetry.md](agents/telemetry.md)).

## It worked if…

- Path A / Compose **dev**: `GET http://127.0.0.1:${API_HOST_PORT:-8000}/health` returns `{"status":"ok"}` (even if Ollama is down).
- After a successful LLM suggest, `GET …/metrics` includes `gen_ai_client_operation_duration_seconds`, `gen_ai_client_request_count_total` (`success`), and `suggest_source_total` ([agents/telemetry.md](agents/telemetry.md)).
- Compose **prod**: the board loads at the client host port and **AI** still returns a suggestion (nginx proxies `/suggest`).
- Arrow keys or swipe move tiles and update score; **AI** in **Expectimax** works without Ollama and shows a per-direction score line; **LLM** returns a suggestion when Ollama is up; **Play** applies the move.

## Useful checks

```bash
# server/
uv run pytest && uv run ruff format --check . && uv run ruff check .

# client/
npm test && npm run lint && npm run build
```

Env pitfalls, multi-checkout ports, Linux Docker + Ollama, rate limits, and image builds: [agents/runtime.md](agents/runtime.md).

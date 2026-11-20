# Getting started

Two ways to run: local processes (typical while hacking) or Compose profiles.

## Prerequisites

- Node.js + npm (client)
- Python ≥ 3.11 with [uv](https://github.com/astral-sh/uv) or pip (server)
- [Ollama](https://ollama.com) on the host, with the model in `OLLAMA_MODEL` (default `gemma4:latest`)
- Docker (optional, for Compose)

## Path A — local processes

```bash
cp .env.example .env   # optional; set API_HOST_PORT / CLIENT_HOST_PORT if 8000/5173 are taken

# 1. Ollama listening on http://localhost:11434

# 2. API (use the same API_HOST_PORT as .env)
cd server
cp .env.example .env   # optional; keep CLIENT_HOST_PORT in sync
uv sync --extra dev
uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_HOST_PORT:-8000}"

# 3. Client (Vite reads repo-root .env for CLIENT_HOST_PORT / API_HOST_PORT)
cd client
npm install
npm run dev
```

Open `http://127.0.0.1:${CLIENT_HOST_PORT:-5173}`. The page calls same-origin `/suggest`; Vite proxies it to the API host port unless `VITE_API_BASE_URL` is set.

## Path B — Compose

```bash
cp .env.example .env   # set COMPOSE_PROJECT_NAME + ports for this worktree
docker compose --profile dev up    # API + Vite
# or
docker compose --profile prod up   # nginx client; API unpublished
# optional scrapers:
docker compose --profile dev --profile metrics up
```

`docker compose up` with no profile starts nothing. Published ports are loopback-only. Defaults are API `8000` and client `5173` (override with `API_HOST_PORT` / `CLIENT_HOST_PORT`); with `metrics`, also Prometheus / Grafana (`PROMETHEUS_HOST_PORT` / `GRAFANA_HOST_PORT`). Prod publishes only the client; nginx forwards `/suggest`.

## It worked if…

- Path A / Compose **dev**: `GET http://127.0.0.1:${API_HOST_PORT:-8000}/health` returns `{"status":"ok"}` (even if Ollama is down).
- After a successful LLM suggest, `GET …/metrics` includes `gen_ai_client_operation_duration_seconds` and `gen_ai_client_request_count_total`.
- Compose **prod**: the board loads at the client host port and **AI** still returns a suggestion (nginx proxies `/suggest`).
- The board loads; arrow keys or swipe move tiles and update score.
- **AI** (LLM) returns a suggestion when Ollama and the model are up; **Play** applies that move.

## Useful checks

```bash
# server/
pytest
ruff format --check . && ruff check .

# client/
npm test
npm run lint
npm run build
```

Env pitfalls, worktree ports, Linux Docker + Ollama, rate limits, and image builds: [agents/runtime.md](agents/runtime.md).

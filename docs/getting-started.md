# Getting started

Two ways to run: local processes (typical while hacking) or Compose profiles.

## Prerequisites

- Node.js + npm (client)
- Python ≥ 3.11 with [uv](https://github.com/astral-sh/uv) or pip (server)
- [Ollama](https://ollama.com) on the host, with the model in `OLLAMA_MODEL` (default `gemma4:latest`)
- Docker (optional, for Compose)

## Path A — local processes

```bash
# 1. Ollama listening on http://localhost:11434

# 2. API
cd server
cp .env.example .env   # optional
uv sync --extra dev
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 3. Client
cd client
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The page calls same-origin `/suggest`; Vite proxies it to `http://127.0.0.1:8000` unless `VITE_API_BASE_URL` is set.

## Path B — Compose

```bash
cp .env.example .env   # optional; see notes in that file
docker compose --profile dev up    # API + Vite (API on :8000)
# or
docker compose --profile prod up   # nginx client on :5173; API unpublished
```

`docker compose up` with no profile starts nothing. Published ports are loopback-only. Dev publishes API `8000` and client `5173`. Prod publishes only the client (`5173`); nginx forwards `/suggest` to the API on the Compose network.

## It worked if…

- Path A / Compose **dev**: `GET http://127.0.0.1:8000/health` returns `{"status":"ok"}` (even if Ollama is down).
- Compose **prod**: the board loads at `http://127.0.0.1:5173` and **AI** still returns a suggestion (nginx proxies `/suggest`).
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

Env pitfalls, Linux Docker + Ollama, rate limits, and image builds: [agents/runtime.md](agents/runtime.md).

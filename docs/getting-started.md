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

Open `http://127.0.0.1:5173`. The page calls `http://localhost:8000` unless `VITE_API_BASE_URL` is set.

## Path B — Compose

```bash
cp .env.example .env   # optional; see notes in that file
docker compose --profile dev up    # API + Vite
# or
docker compose --profile prod up   # API + nginx static client
```

`docker compose up` with no profile starts nothing. Published ports are loopback-only (`8000` API, `5173` client).

## It worked if…

- `GET http://127.0.0.1:8000/health` returns `{"status":"ok"}` (even if Ollama is down).
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

Env pitfalls, Linux Docker + Ollama, and image builds: [agents/runtime.md](agents/runtime.md).

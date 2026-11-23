# 2048 with AI suggestions

Single-player 2048 with an optional AI coach (**LLM** via Ollama or **Expectimax**), **Auto Play**, and local ops (Phoenix traces + Prometheus / Grafana).

```mermaid
flowchart LR
  Browser["Browser<br/>React + Vite"]
  API["API<br/>FastAPI"]
  Ollama["Ollama<br/>host model"]
  Browser -->|"same-origin /suggest"| API
  API -->|"chat"| Ollama
```

- Play classic 2048 (keys or swipe): random opening **2**s (1–16), hard win at **2048**, score + session best.
- Ask for a suggestion (LLM or Expectimax with per-direction scores), confirm with **Play**, or ignore and move yourself.
- **Auto Play** applies suggestions in a loop until you **Stop** (retries on model busy or fallback; stops on spend-cap 429).
- Optional ops: host Phoenix for per-request traces; Compose `--profile metrics` for Prometheus / Grafana.

## Quick start

```bash
# Terminal 1 — API
cd server && uv sync --extra dev && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port "${API_HOST_PORT:-8000}"
# Terminal 2 — Client
cd client && npm install && npm run dev
```

Open `http://127.0.0.1:${CLIENT_HOST_PORT:-5173}` (or run `cp .env.example .env && docker compose --profile dev up`; see [getting started](docs/getting-started.md)). **Expectimax** works out of the box with no model setup; start [Ollama](https://ollama.com) on the host (`OLLAMA_MODEL`, default `gemma4:latest`) for **LLM** mode.

## Docs

| Audience | Start here |
|---|---|
| **Humans** — what this is and how it’s built | [docs/](docs/README.md) |
| **Pitch page** — diagram-heavy walkthrough (GitHub Pages) | [Live site](https://christycty.github.io/game-2048/) · [source](site/index.html) |
| **Agents** — rules, invariants, implementation detail | [AGENTS.md](AGENTS.md) → [docs/agents/](docs/agents/README.md) |

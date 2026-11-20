# Agent entrypoint

2048 in the browser with optional AI move suggestions (confirm before play).

## Doc map (read this first)

| Need | Go here |
|---|---|
| **How to write / where to put docs** | [docs/agents/writing-docs.md](docs/agents/writing-docs.md) |
| Human overview / diagrams | [docs/](docs/README.md) |
| Product rules | [docs/agents/prd.md](docs/agents/prd.md) |
| Client / server / runtime detail | [docs/agents/](docs/agents/README.md) |
| Review heuristics | [docs/agents/review-patterns/](docs/agents/review-patterns/client-anti-patterns.md) |

Human docs are orientation only. **Implementation truth is under `docs/agents/`.** When docs and code disagree, fix the canonical agent page and the code together.

## Goals

1. Tile spawn: two **2**s on random empty cells at start; after each board-changing move, spawn a **2** or **4** on a random empty cell.
2. Surface: current score, session best, new game only—no undo or leaderboard.
3. AI suggestions on the server: client sends board + mode; server returns a suggested move. Multiple modes over time; LLM first (Expectimax may be a stub).

## Client

- Vite + JS. Game rules in `game.js`; UI in components; suggest HTTP in `api.js`.
- PRs with visible UI changes: attach one clear screenshot to the PR summary. Full desktop viewport (~800px+); verify no tiling/cropping artifacts; show the new UI state.

## Server

- Python FastAPI + Pydantic. Prefer clear types, solid tests, and (when adding observability) OpenTelemetry. Keep a proper client abstraction for the model.

## Documentation changes

Follow [docs/agents/writing-docs.md](docs/agents/writing-docs.md): keep human pages short and diagram-led; put paths, invariants, and edge cases under `docs/agents/`; one source of truth per fact.

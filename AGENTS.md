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
3. AI suggestions on the server: client sends board + mode; server returns a suggested move. Modes today: LLM and depth-limited Expectimax (score-line reason).

## Client

- Vite + JS. Game rules in `game.js`; UI in components; suggest HTTP in `api.js`.

## Server

- Python FastAPI + Pydantic. Prefer clear types and solid tests. Tracing is wired (Phoenix / OpenInference OTLP via `app/telemetry.py`; traces only—no scrape `/metrics` on mainline; see [docs/agents/server.md](docs/agents/server.md)). Keep a proper client abstraction for the model.

## Pull requests

Fill the PR body from [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md) (Summary / Test plan / Verify / Docs).

- In the **PR body**, use **repo-root paths** in links (e.g. `docs/agents/writing-docs.md`). Do not use `../…` — those paths are only valid inside files on disk, not in GitHub PR markdown.
- **Verify is per subsection** (UI / API / docs-only): mark N/A only where it does not apply, with a one-line why; still paste real evidence for what does (screenshots in the summary, `curl` transcripts, script output). Do not invent evidence.
- Visible UI: full desktop viewport (~800px+); no CDP clip / tiling artifacts; show the **new** state, not only the default board.

## Documentation changes

Follow [docs/agents/writing-docs.md](docs/agents/writing-docs.md): keep human pages short and diagram-led; put paths, invariants, and edge cases under `docs/agents/`; one source of truth per fact.

Behavior/runtime changes belong in the **same PR** as the canonical agent doc update (see the Docs section of the PR template). Before finishing:

```bash
cd scripts && python -m unittest discover -v -s . -p 'test_*.py'
python scripts/check_doc_links.py        # fails CI on broken relative links
python scripts/check_docs_freshness.py   # warns only; satisfy with docs/agents/ or AGENTS.md (human docs/*.md alone is not enough)
```

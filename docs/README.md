# Documentation

Human-facing docs for this project. Concise, high-level, diagram-first.

Building or changing code? Start at [../AGENTS.md](../AGENTS.md) and [agents/](agents/README.md). Those pages are the implementation source of truth—do not treat this tree as a coding spec.

| Doc | Purpose |
|---|---|
| [overview.md](overview.md) | What the product is, who it’s for, the player journey |
| [architecture.md](architecture.md) | How the pieces fit (topology, request path, stack) |
| [getting-started.md](getting-started.md) | Run locally or with Compose |
| [agents/](agents/README.md) | Agent rules, deep detail, review patterns, **how to write docs** |

CI `docs` job: script unit tests, `check_doc_links.py`, and a freshness nudge when code changes without `docs/agents/`. Details: [agents/writing-docs.md](agents/writing-docs.md).

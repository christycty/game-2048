# Writing documentation

Conventions for this repo. Follow them when adding or editing docs so humans and agents keep getting the right depth.

## Two audiences, two trees

| Tree | Audience | Job |
|---|---|---|
| `docs/*.md` (and root `README.md`) | Humans learning the project | What it is, how pieces fit, how to run |
| `docs/agents/**` (+ root `AGENTS.md`) | Agents and implementers | Rules, invariants, paths, edge cases |

Same *topics* may appear in both trees with **different depth**. Do not “humanize” an agent doc by softening tone—**split** instead: short diagram page for humans, precise detail for agents.

Cross-link once at the top of a page when useful. Never duplicate facts (ports, env names, stack choices) in both trees; pick one canonical home and link.

## Human docs (`docs/`)

**Feel:** concise, clean, high-level, diagram-heavy. Skimmable in minutes.

**Allowed set (keep this small):**

| File | Purpose |
|---|---|
| Root `README.md` | Front door: one sentence, one diagram, quick start, links |
| `docs/README.md` | Index of the human tree |
| `docs/overview.md` | Product story + player journey |
| `docs/architecture.md` | Topology, request path, coarse modules, stack |
| `docs/getting-started.md` | Run paths + “it worked if…” |

Do **not** add human `client.md` / `server.md` unless each stays ~½ page + one diagram. Prefer pointing at architecture + agents detail.

**Length budget (soft max):**

| Doc | Lines |
|---|---|
| Root `README.md` | ~40–60 |
| `overview.md` | ~80 + 1–2 diagrams |
| `architecture.md` | ~100 + 2–3 diagrams |
| `getting-started.md` | ~60 |

If a human section has **no diagram and more than ~15 lines**, it probably belongs under `docs/agents/`.

**Diagrams:** Prefer Mermaid in Markdown. Reuse a small set—system context, suggest sequence, coarse module map, deploy profiles. One real UI screenshot in the root README or overview is fine; avoid diagram spam.

**Human pages must not include:** per-file layout tables, settle timers, pointer-capture rules, full env matrices, test file inventories, retry/budget internals.

## Agent docs (`docs/agents/`)

**Feel:** precise, path-heavy, checklist-friendly. Current truth only.

**Canonical detail pages:** `prd.md`, `client.md`, `server.md`, `runtime.md`, plus `review-patterns/`.

**Root `AGENTS.md`:** short entrypoint (goals, hard rules, pointers). Keep it scannable; put depth in `docs/agents/`. Always link [writing-docs.md](writing-docs.md) so future agents inherit these conventions.

**Prefer:**

- Constraints and invariants (“no Vite proxy”, “best score is session-only”)
- Tables for behavior, HTTP, settings, layout
- “Not built yet” / “Not in this layout” sections
- Commands that actually run in this repo

**Avoid:**

- Mixing *plan* with *truth* (put staged plans under `plan/` or mark clearly as non-canonical)
- Conflicting copies of the same fact across packages or old `doc/` paths
- Essay-length narrative that duplicates human overview

## Truth vs intent vs plan

| Kind | Where | Example |
|---|---|---|
| **Truth** | `runtime.md`, `client.md`, `server.md` | Current ports, env names, pipeline |
| **Intent** | `prd.md`, human `overview.md` | Goals, non-goals, success criteria |
| **Plan** | `plan/` or dated notes | Future metrics stages—must not override truth |

## One source of truth

- Ports, Compose profiles, env names → `docs/agents/runtime.md` (human getting-started summarizes and links).
- Product rules → `docs/agents/prd.md` (human overview summarizes and links).
- API shapes → code (Pydantic / OpenAPI) + `docs/agents/server.md` summary.
- Executable checks → tests and CI; docs describe intent, tests prove it.

When behavior changes, update the **canonical agent page first**, then trim the human summary if the story changed.

## Review patterns

Short anti-pattern notes under `docs/agents/review-patterns/` are encouraged. Prefer concrete “prefer X over Y” bullets over philosophy.

## Keeping docs high quality and up to date

### Same PR as the code

If behavior, API shapes, env names, ports, Compose, or product non-goals change, update the **canonical agent page in the same PR**. Touch human pages only when a newcomer’s story or diagram would otherwise lie.

PR authors fill the Docs section in [`.github/PULL_REQUEST_TEMPLATE.md`](../../.github/PULL_REQUEST_TEMPLATE.md). Mark **Docs N/A** only for changes that do not affect users, runtime, or product rules (and say why).

### PR Verify screenshots

Evidence goes **in the PR summary**, not only as a separate comment. Apply to client UI **and** ops UIs (Grafana, Prometheus, `/metrics` text).

| Do | Don't |
|---|---|
| Frame the **new** state (mode + suggestion + Play; GenAI series; dashboard with data) | Default board / empty panels “because the page loads” |
| Width ≥ ~800px of real content | Phone-narrow strips |
| Crop to the useful region (autocrop letterboxing / huge empty dark margins) | Tall square captures with the UI in a thin band at the top |
| Prefer a focused view when the full page is mostly noise (e.g. GenAI lines from `/metrics`, Grafana panels) | Paste an entire raw `/metrics` dump dominated by unrelated HTTP series |
| Attach via `gh pr edit --attach` (one file at a time) and embed the image markdown **under Verify → UI** | Leave screenshots only in a comment |

Browser automation often pads to a large canvas. **Inspect the PNG before upload**: if most of the image is empty, crop or re-shoot. Avoid CDP `clip` / `captureBeyondViewport` crops that tile or duplicate UI.

### Freshness by doc kind

| Kind | Bar | How |
|---|---|---|
| Truth (`runtime`, `client`, `server`) | Match `main` | Same PR as code |
| Intent (`prd`, overview) | Match product decisions | Update when goals/non-goals change |
| How-to (getting-started) | Commands work | “It worked if…”; occasional smoke |
| Diagrams (architecture) | Topology/API shape | Update on structural change |
| Plan (`plan/`) | May rot | Never treat as truth; date or mark draft |

### Prefer executable truth

- API request/response → Pydantic / OpenAPI; `server.md` summarizes
- Env names → `.env.example`; `runtime.md` explains why
- Ports / profiles → Compose + CI; docs state intent
- Product rules that matter → tests; PRD states success criteria

### Automation in this repo

| Check | What it does |
|---|---|
| `scripts/check_doc_links.py` | Fails CI if relative Markdown links under docs entrypoints are broken |
| `scripts/check_docs_freshness.py` | **Warns** (does not fail) when `client/`, `server/`, Compose, env example, or workflows change without `docs/agents/` or `AGENTS.md` |
| `scripts/test_*.py` | Pinned unit tests for the scripts above (stdlib `unittest`, no extra deps) |

The `docs` CI job (Python **3.12**) runs the unit tests first, then the two scripts. Locally:

```bash
cd scripts && python -m unittest discover -v -s . -p 'test_*.py'
python scripts/check_doc_links.py
python scripts/check_docs_freshness.py
```

### Definition of done (feature / behavior change)

1. Code + tests match the new behavior
2. Canonical file under `docs/agents/` updated (or Docs N/A noted on the PR)
3. Human page updated only if the story/diagram would lie
4. No second copy of the same fact
5. `python3 scripts/check_doc_links.py` passes

### Agents maintaining docs

- After a feature change: diff against `docs/agents/{prd,client,server,runtime}.md` and patch only what changed
- Do **not** regenerate all docs from scratch—that wipes careful constraints
- Prefer deleting duplicate facts over expanding human pages past the length budget

## Checklist before merging doc changes

1. Is this page in the right tree (human vs agent)?
2. Did I introduce a second home for the same fact?
3. Human page still within length budget and diagram-led?
4. Agent page states current truth, not a wish?
5. Links from `docs/README.md` / `docs/agents/README.md` / root `AGENTS.md` still work?
6. Link check script passes?

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

## Checklist before merging doc changes

1. Is this page in the right tree (human vs agent)?
2. Did I introduce a second home for the same fact?
3. Human page still within length budget and diagram-led?
4. Agent page states current truth, not a wish?
5. Links from `docs/README.md` / `docs/agents/README.md` / root `AGENTS.md` still work?

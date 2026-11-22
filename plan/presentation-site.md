# Presentation site (GitHub Pages)

**Status:** Scaffolding on branch `presentation-site` / worktree `game-2048-present` (`site/`, Pages workflow, AGENTS/getting-started polish started). Independent of residual ops WIP.  
**Related:** [overview.md](./overview.md) (status board + presentability caveats).

## Goal

A **technical walkthrough for a code-exercise interviewer**, hosted on GitHub Pages — not a marketing hero page and not a second copy of `docs/agents/`. Easy to skim: topology, cancel, trace/beacons, metrics, with code snippets and UI/dashboard figures.

`docs/*.md` stay the repo handbook. `AGENTS.md` / `docs/agents/` stay the implementation source of truth. This site is the **reviewer front door**.

## Non-goals

- Live game embed that calls a production API (Pages is static; demo stays local/Compose).
- Replacing Grafana/Phoenix UIs.
- Marketing blog, blog CMS, or heavy SPA framework unless static generation stays trivial.
- Auth, custom domain, or analytics beyond what Pages gives by default.

## Audience & story (one arc)

1. **What** — single-player 2048 + optional AI coach (LLM / Expectimax) + Auto Play.
2. **How it fits** — browser → same-origin proxy → FastAPI → Ollama (host); Expectimax never needs the model.
3. **Why it’s “practice,” not a toy** — cancel on abandon, rate limits + LLM in-flight gate, traces vs scrape metrics, thin client beacons.
4. **How to try** — link to repo README / getting-started; call out Ollama + optional Phoenix/Grafana for the full walkthrough.

## Shape

| Choice | Decision |
| --- | --- |
| Location | Repo-root `site/` (keeps `docs/` as markdown handbook) |
| Stack | Static HTML + CSS (+ small JS). Mermaid via CDN or pre-rendered SVG for critical diagrams |
| Hosting | GitHub Pages from `site/` (Actions upload artifact; no `gh-pages` branch required) |
| Tone | One composition per viewport section; diagram-first; brand “2048” / product name hero-level |
| Motion | 2–3 intentional reveals/transitions — presence, not noise |

### Page outline (v1)

1. Compact header + TOC (no decorative hero).
2. Stack table → topology diagram.
3. Client surface (UI schematic + `api.js` snippet).
4. Suggest path + cancel sequence + code.
5. Traceparent / beacons snippets.
6. Grafana panel map + PromQL; slots for real screenshots in `site/assets/`.
7. Verify checklist for the interviewer.

## Presentability polish (ship with or just before Pages)

These are narrative fixes, not new product features. Do them so the pitch page and repo don’t contradict each other:

| Item | Why |
| --- | --- |
| Fix `AGENTS.md` “traces only—no scrape `/metrics`” | False on `main`; embarrasses a walkthrough |
| Refresh [production-practice-review.md](./production-practice-review.md) or mark historical | Still reads like metrics/cancel aren’t shipped |
| Demo prep blurb in getting-started / site “Try it” | Phoenix not in Compose; full GenAI+ops story needs a prepared host |
| Remove or ignore leftover parent dirs | `game-2048-auto-play/`, `game-2048-metrics/` look unfinished if the parent folder is opened |

Prefer a thin docs PR (or commits on this branch) over letting the site paper over stale agent docs.

## Implementation sketch

| Piece | Notes |
| --- | --- |
| `site/index.html` | Single-page sections above; semantic landmarks |
| `site/styles.css` | CSS variables; distinctive type; atmospheric background — not a flat white doc dump |
| Diagrams | Prefer Mermaid sources kept in-page (or `site/diagrams/`) so architecture stays editable |
| `.github/workflows/pages.yml` | Build/copy `site/` → Pages artifact on `main` (or this branch while previewing) |
| README link | One line under Docs: “Presentation” → Pages URL once live |
| CI | Optional link-check for `site/` absolute repo links; don’t block game CI on Pages |

## Verify

- Open `site/index.html` locally (or Pages preview): hero reads as one composition; diagrams render; mobile doesn’t collapse into a wall of text.
- After polish: `AGENTS.md` metrics line matches `docs/agents/server.md` / telemetry.
- Pages workflow green; site URL linked from README.

## Sequencing

- **Can start now** in parallel with residual ops (`llm-rate-limit-layers`, `cancel-observability`, `client-events-integrity`).
- Prefer merging the site after residual ops so diagrams don’t describe cancel/beacon gaps that are about to close — or label “in flight” clearly until those land.
- Presentability polish can land on this branch or a tiny docs PR; don’t block Pages scaffolding on it.

## Summary

<!-- What changed and why (1–3 bullets). -->

## Test plan

- [ ] Relevant automated tests pass locally (or CI covers them)

## Verify

Paste evidence here so reviewers do not have to re-run everything. **N/A is per subsection** below—mark only what does not apply, with a one-line why; still attach real evidence for what does.

### UI (when the page or controls change)

- [ ] Screenshot(s) attached **in this summary** (not only as a separate comment)
- Capture: ≥~800px of real content; crop letterboxing / empty margins; no CDP clip / tiling artifacts; show the **new** state (e.g. mode + suggestion + Play, or Grafana panels with data), not only the default / empty view
- Quality bar: `docs/agents/writing-docs.md` → **PR Verify screenshots**
- [ ] UI N/A — why:

<!-- Drag images below, or: gh pr edit --attach … -->

### API / runtime (when the server, suggest path, health, or Compose/env changes)

- [ ] `curl` (or equivalent) output pasted below for the paths you touched
- [ ] API / runtime N/A — why:

```bash
# Examples — keep only what applies; paste command + response
curl -sS http://127.0.0.1:8000/health
curl -sS -X POST http://127.0.0.1:8000/suggest \
  -H 'content-type: application/json' \
  -d '{"board":[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,2]],"mode":"llm"}'
```

<!-- Paste transcripts below -->

### Docs-only / no user-visible or runtime change

- [ ] Docs-only verify — paste script output or note N/A with why:

## Docs

Same PR should keep docs honest. Guide: `docs/agents/writing-docs.md` (use that repo-root path when linking from the PR body).

- [ ] Behavior, API, env, ports, Compose, or product rules changed → updated the **canonical** page under `docs/agents/` (or root `AGENTS.md`)
- [ ] Newcomer-facing story/diagram would otherwise lie → updated `docs/overview.md`, `docs/architecture.md`, and/or `docs/getting-started.md`
- [ ] No second home for the same fact
- [ ] Docs N/A for this PR (typo-only, pure refactor with no user/runtime change, etc.) — leave a one-line note below

<!-- If Docs N/A: why -->

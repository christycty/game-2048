# Cancel observability — Grafana verify shots

Captured against Compose `--profile dev --profile metrics` on the
`cancel-observability` worktree after e2e + live traffic (client cancel
beacons, mid-suggest disconnect → HTTP `499` / GenAI `cancelled`).

Shots are cropped to the cancel-proof panels. The full-width **In-flight
HTTP requests** gauge is often a flat zero while idle or when `/suggest`
finishes between Prometheus scrapes — that is expected, not a cancel
regression (see [telemetry.md](../agents/telemetry.md)).

| Shot | What it proves |
| --- | --- |
| [cancel-obs-grafana-api-client.png](./cancel-obs-grafana-api-client.png) | API **POST /suggest by status** shows **499** alongside 200 / 429 |
| [cancel-obs-grafana-client-cancel.png](./cancel-obs-grafana-client-cancel.png) | Client row charts **cancel** / fail / rate_limit |
| [cancel-obs-grafana-llm-cancelled.png](./cancel-obs-grafana-llm-cancelled.png) | LLM outcomes include **cancelled**; success rate stays 100% (cancelled excluded) |

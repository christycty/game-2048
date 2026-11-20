# Observability configs

Compose files for the optional `--profile metrics` stack (Prometheus + Grafana).

**Canonical run notes, ports, and env pitfalls:** [docs/agents/runtime.md](../docs/agents/runtime.md).  
**API series and settings:** [docs/agents/server.md](../docs/agents/server.md).

```bash
docker compose --profile dev --profile metrics up
# Grafana GenAI ops: http://127.0.0.1:${GRAFANA_HOST_PORT:-3000}/d/game2048-genai
```

Telemetry inventory (every signal; Phoenix vs Prometheus/Grafana; GenAI ops panel → series map, including p50/p95 and legend `> 0` rate filters): [docs/agents/telemetry.md](../docs/agents/telemetry.md).

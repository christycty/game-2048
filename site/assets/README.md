# Presentation assets

| File | Content |
| --- | --- |
| `ui-suggest.png` | Live game UI (Expectimax hint + Play) |
| `phoenix-trace.png` | Phoenix Traces: `POST /suggest` → `suggest` → `ollama chat` |
| `phoenix-span-detail.png` | Phoenix span detail after opening a root `POST /suggest` (Input / Output) |
| `grafana-api.png` | Grafana GenAI ops — earlier 4-panel API row reference capture (`status`, `source`, `latency`, `in-flight`); current provisioned row adds a 5th `Suggest limit rejects (capacity vs spend)` panel beside `in-flight` |
| `grafana-client.png` | Grafana GenAI ops — Client row capture during a rate-limit burst showing active `fail` and `rate_limit` series (`sum by (outcome) (rate(client_suggest_outcome_total[5m])) > 0` hides zero-rate outcomes until `model_busy` or `cancel` fire) |
| `grafana-llm.png` | Grafana GenAI ops — LLM row (`success`, `outcome`, `errors`, `duration`, `tokens`) |

Referenced from [index.html](../index.html) (inline client preview + collapsible `<details>` blocks).

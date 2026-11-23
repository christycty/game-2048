# Expectimax Auto Play rate cap — verify shots (PR #25)

Captured against Compose `--profile dev` on `fix/expectimax-autoplay-rate-cap`
after `docker compose up -d --force-recreate --build` with
`CLIENT_HOST_PORT=5185` / `API_HOST_PORT=8000`.

## Env after recreate

```
SUGGEST_RATE_LIMIT_EXPECTIMAX_REQUESTS=360
SUGGEST_RATE_LIMIT_REQUESTS=60
LLM_MAX_IN_FLIGHT=1
```

## Four-tab browser soak (>1 min)

Four tabs at `http://127.0.0.1:5185/`, each on **Expectimax** + **Auto Play**.
No UI “Too many suggestions”; Stop stayed pressed; expectimax score hints kept updating.

| Shot | Tab |
| --- | --- |
| [tab1-expectimax-autoplay.png](./tab1-expectimax-autoplay.png) | Expectimax Auto Play still running |
| [tab2-expectimax-autoplay.png](./tab2-expectimax-autoplay.png) | Expectimax Auto Play still running |
| [tab3-expectimax-autoplay.png](./tab3-expectimax-autoplay.png) | Expectimax Auto Play still running |
| [tab4-expectimax-autoplay.png](./tab4-expectimax-autoplay.png) | Expectimax Auto Play still running |

Metrics during/after soak: `suggest_source_total{suggest_source="expectimax"}` climbed
(e.g. 68 → 271 over ~1 min of four-tab play; later ~359). No
`suggest_limit_reject` / spend-429 series appeared. `/suggest` HTTP samples were **200** only.

# PR #21 — client-events integrity verify

Live API on loopback with tight caps (`CLIENT_EVENTS_RATE_LIMIT_REQUESTS=3`,
`SUGGEST_RATE_LIMIT_REQUESTS=1`) plus contract tests.

| Artifact | What it proves |
| --- | --- |
| [api-transcript.txt](./api-transcript.txt) | Under-cap `204`, over-cap `429` + `Retry-After`, scrape stays flat, suggest ↔ beacon independence |
| [metrics-after-burst.png](./metrics-after-burst.png) | After 3 admits + 5 over-cap fails, `fail` series still **1.0** |
| [over-cap-429.png](./over-cap-429.png) | Over-cap response shape (`429`, `Retry-After: 60`, `too many client events`) |

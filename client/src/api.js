// Calls the suggestion API. The board is a 4x4 of tile values; mode is llm or expectimax.
// The default URL is same-origin /suggest. Vite and the prod nginx both forward it.
// VITE_API_BASE_URL replaces that with an absolute origin.
// Each suggest sends W3C `traceparent` so Phoenix can tie UI → API → LLM.
// Fail / 429 outcomes beacon to /client-events for scrapeable client counts.

import { createTraceparent } from "./trace.js";

function apiBaseUrl() {
    return import.meta.env?.VITE_API_BASE_URL ?? "";
}

export class SuggestError extends Error {
    constructor(message, { status } = {}) {
        super(message);
        this.name = "SuggestError";
        this.status = status;
    }
}

function reportClientOutcome(outcome, { fetch: fetchImpl = fetch } = {}) {
    try {
        void fetchImpl(`${apiBaseUrl()}/client-events`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ outcome }),
            keepalive: true,
        }).catch(() => {});
    } catch {
        // Beacon must never affect suggest UX.
    }
}

export async function suggestMove(board, mode = "llm", { fetch: fetchImpl = fetch } = {}) {
    const traceparent = createTraceparent();
    let response;
    try {
        response = await fetchImpl(`${apiBaseUrl()}/suggest`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                traceparent,
            },
            body: JSON.stringify({ board, mode }),
        });
    } catch {
        reportClientOutcome("fail", { fetch: fetchImpl });
        throw new SuggestError("suggestion request failed", { status: 0 });
    }

    if (!response.ok) {
        reportClientOutcome(response.status === 429 ? "rate_limit" : "fail", {
            fetch: fetchImpl,
        });
        throw new SuggestError("suggestion request failed", { status: response.status });
    }

    let body;
    try {
        body = await response.json();
    } catch {
        reportClientOutcome("fail", { fetch: fetchImpl });
        throw new SuggestError("suggestion response was unusable");
    }
    if (!body || typeof body.move !== "string") {
        reportClientOutcome("fail", { fetch: fetchImpl });
        throw new SuggestError("suggestion response was unusable");
    }
    return body;
}

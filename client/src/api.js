// Calls the suggestion API. The board is a 4x4 of tile values; mode is llm or expectimax.
// The default URL is same-origin /suggest. Vite and the prod nginx both forward it.
// VITE_API_BASE_URL replaces that with an absolute origin.
// Each suggest sends W3C `traceparent` so Phoenix can tie UI → API → LLM.
// Fail / 429 outcomes beacon to /client-events for scrapeable client counts.
// Pass shouldReportOutcome when the UI can abandon the request (stale token);
// abandoned fails must not inflate client Grafana rates. Abort stays silent (no fail beacon).

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

export function isAbortError(error) {
    return Boolean(error) && error.name === "AbortError";
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

function maybeReportOutcome(
    outcome,
    { fetch: fetchImpl = fetch, shouldReportOutcome = () => true } = {},
) {
    if (!shouldReportOutcome()) return;
    reportClientOutcome(outcome, { fetch: fetchImpl });
}

export async function suggestMove(
    board,
    mode = "llm",
    { fetch: fetchImpl = fetch, signal, shouldReportOutcome = () => true } = {},
) {
    const reportOpts = { fetch: fetchImpl, shouldReportOutcome };
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
            signal,
        });
    } catch (error) {
        // Abort must stay AbortError so the UI can stay silent (Stop, New Game, move, mode).
        if (isAbortError(error) || signal?.aborted) {
            throw isAbortError(error) ? error : new DOMException("Aborted", "AbortError");
        }
        maybeReportOutcome("fail", reportOpts);
        throw new SuggestError("suggestion request failed", { status: 0 });
    }

    // 499 = server saw disconnect; treat like abort (silent) even if fetch resolved a body.
    if (signal?.aborted || response.status === 499) {
        throw new DOMException("Aborted", "AbortError");
    }

    if (!response.ok) {
        maybeReportOutcome(response.status === 429 ? "rate_limit" : "fail", reportOpts);
        throw new SuggestError("suggestion request failed", { status: response.status });
    }

    let body;
    try {
        body = await response.json();
    } catch (error) {
        if (isAbortError(error) || signal?.aborted) {
            throw isAbortError(error) ? error : new DOMException("Aborted", "AbortError");
        }
        maybeReportOutcome("fail", reportOpts);
        throw new SuggestError("suggestion response was unusable");
    }
    if (!body || typeof body.move !== "string") {
        maybeReportOutcome("fail", reportOpts);
        throw new SuggestError("suggestion response was unusable");
    }
    return body;
}

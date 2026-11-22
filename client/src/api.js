// Calls the suggestion API. The board is a 4x4 of tile values; mode is llm or expectimax.
// The default URL is same-origin /suggest. Vite and the prod nginx both forward it.
// VITE_API_BASE_URL replaces that with an absolute origin.
// Each suggest sends W3C `traceparent` so Phoenix can tie UI → API → LLM.
// Fail / 429 / cancel outcomes beacon to /client-events for scrapeable client counts.
// Pass shouldReportOutcome when the UI can abandon the request (stale token);
// abandoned fails must not inflate client Grafana rates. Abort beacons `cancel`
// (not fail); maybeReportOutcome still skips fail/rate_limit when the signal aborted.

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

function reportCancel({ fetch: fetchImpl = fetch } = {}) {
    // Abort itself is the abandon signal — do not gate on shouldReportOutcome
    // (Stop/move/New Game bump the token before fetch rejects).
    reportClientOutcome("cancel", { fetch: fetchImpl });
}

function maybeReportOutcome(
    outcome,
    { fetch: fetchImpl = fetch, signal, shouldReportOutcome = () => true } = {},
) {
    // Abort may land across an await (e.g. during response.json); never beacon fail/429 then.
    if (signal?.aborted || !shouldReportOutcome()) return;
    reportClientOutcome(outcome, { fetch: fetchImpl });
}

function abortError(error) {
    return isAbortError(error) ? error : new DOMException("Aborted", "AbortError");
}

export async function suggestMove(
    board,
    mode = "llm",
    { fetch: fetchImpl = fetch, signal, shouldReportOutcome = () => true } = {},
) {
    const reportOpts = { fetch: fetchImpl, signal, shouldReportOutcome };
    const cancelOpts = { fetch: fetchImpl };
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
            reportCancel(cancelOpts);
            throw abortError(error);
        }
        maybeReportOutcome("fail", reportOpts);
        throw new SuggestError("suggestion request failed", { status: 0 });
    }

    // 499 = server saw disconnect; treat like abort (silent UX) even if fetch resolved a body.
    if (signal?.aborted || response.status === 499) {
        reportCancel(cancelOpts);
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
            reportCancel(cancelOpts);
            throw abortError(error);
        }
        maybeReportOutcome("fail", reportOpts);
        throw new SuggestError("suggestion response was unusable");
    }
    // Abort across json() must stay silent even when the body is also unusable.
    if (signal?.aborted) {
        reportCancel(cancelOpts);
        throw new DOMException("Aborted", "AbortError");
    }
    if (!body || typeof body.move !== "string") {
        maybeReportOutcome("fail", reportOpts);
        throw new SuggestError("suggestion response was unusable");
    }
    return body;
}

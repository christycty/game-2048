// Calls the suggestion API. The board is a 4x4 of tile values; mode is llm or expectimax.
// The default URL is same-origin /suggest. Vite and the prod nginx both forward it.
// VITE_API_BASE_URL replaces that with an absolute origin.
// Each suggest sends W3C `traceparent` so Phoenix can tie UI → API → LLM.
// Fail / 429 / cancel outcomes beacon to /client-events for scrapeable client counts.
// Pass shouldReportOutcome when the UI can abandon the request (stale token);
// abandoned fails must not inflate client Grafana rates. Abort beacons `cancel`
// (not fail); maybeReportOutcome still skips fail/rate_limit/model_busy when aborted.

import { createTraceparent } from "./trace.js";

/** Spend hard-ceiling 429 (stop Auto Play). */
export const LIMIT_SPEND = "spend";
/** Per-mode capacity-gate 429 (Auto Play may retry). */
export const LIMIT_CAPACITY = "capacity";
export const DETAIL_SPEND_CAP = "too many suggestions";
export const DETAIL_MODEL_BUSY = "model busy";

function apiBaseUrl() {
    return import.meta.env?.VITE_API_BASE_URL ?? "";
}

export class SuggestError extends Error {
    constructor(message, { status, limitReason = null, retryAfter = null } = {}) {
        super(message);
        this.name = "SuggestError";
        this.status = status;
        this.limitReason = limitReason;
        this.retryAfter = retryAfter;
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

function parseRetryAfter(headers) {
    const raw = headers?.get?.("retry-after");
    if (raw == null || raw === "") return null;
    const seconds = Number.parseInt(raw, 10);
    return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

/** Classify a 429 from detail / X-Suggest-Limit; unknown → spend (safe stop). */
export function classifySuggestLimit(detail, headerReason) {
    if (headerReason === LIMIT_CAPACITY || detail === DETAIL_MODEL_BUSY) {
        return LIMIT_CAPACITY;
    }
    return LIMIT_SPEND;
}

async function readSuggestErrorBody(response) {
    try {
        const body = await response.json();
        return typeof body?.detail === "string" ? body.detail : null;
    } catch {
        return null;
    }
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
        if (response.status === 429) {
            const detail = await readSuggestErrorBody(response);
            if (signal?.aborted) {
                reportCancel(cancelOpts);
                throw new DOMException("Aborted", "AbortError");
            }
            const limitReason = classifySuggestLimit(
                detail,
                response.headers?.get?.("x-suggest-limit"),
            );
            const retryAfter = parseRetryAfter(response.headers);
            maybeReportOutcome(
                limitReason === LIMIT_CAPACITY ? "model_busy" : "rate_limit",
                reportOpts,
            );
            throw new SuggestError(
                limitReason === LIMIT_CAPACITY ? DETAIL_MODEL_BUSY : DETAIL_SPEND_CAP,
                { status: 429, limitReason, retryAfter },
            );
        }
        maybeReportOutcome("fail", reportOpts);
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

// Calls the suggestion API. The board is a 4x4 of tile values; mode is llm or expectimax.
// The default URL is same-origin /suggest. Vite and the prod nginx both forward it.
// VITE_API_BASE_URL replaces that with an absolute origin.

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

export async function suggestMove(
    board,
    mode = "llm",
    { fetch: fetchImpl = fetch, signal } = {},
) {
    let response;
    try {
        response = await fetchImpl(`${apiBaseUrl()}/suggest`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ board, mode }),
            signal,
        });
    } catch (error) {
        // Abort must stay AbortError so the UI can stay silent (Stop, New Game, move, mode).
        if (isAbortError(error) || signal?.aborted) {
            const abortError = isAbortError(error) ? error : new DOMException("Aborted", "AbortError");
            throw abortError;
        }
        throw new SuggestError("suggestion request failed", { status: 0 });
    }

    if (!response.ok) {
        throw new SuggestError("suggestion request failed", { status: response.status });
    }

    const body = await response.json();
    if (!body || typeof body.move !== "string") {
        throw new SuggestError("suggestion response was unusable");
    }
    return body;
}

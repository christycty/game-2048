import assert from "node:assert/strict";
import test from "node:test";
import { suggestMove, SuggestError, isAbortError } from "./api.js";

const BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 2],
];

test("suggestMove posts the board and mode, then returns the body", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        return {
            ok: true,
            async json() {
                return { move: "left", mode: "llm", source: "llm", reason: "Merges." };
            },
        };
    };

    const body = await suggestMove(BOARD, "llm", { fetch: fetchImpl });

    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/suggest");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(calls[0].options.body), { board: BOARD, mode: "llm" });
    assert.deepEqual(body, { move: "left", mode: "llm", source: "llm", reason: "Merges." });
});

test("suggestMove passes an AbortSignal through to fetch", async () => {
    const controller = new AbortController();
    let seen;
    const fetchImpl = async (_url, options) => {
        seen = options.signal;
        return {
            ok: true,
            async json() {
                return { move: "left", mode: "llm", source: "llm", reason: "ok" };
            },
        };
    };

    await suggestMove(BOARD, "llm", { fetch: fetchImpl, signal: controller.signal });
    assert.equal(seen, controller.signal);
});

test("suggestMove rejects a failed HTTP response", async () => {
    const fetchImpl = async () => ({ ok: false, status: 409, async json() { return {}; } });

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 409,
    );
});

test("suggestMove reports a rate limit as status 429", async () => {
    const fetchImpl = async () => ({ ok: false, status: 429, async json() { return {}; } });

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 429,
    );
});

test("suggestMove rejects a network failure", async () => {
    const fetchImpl = async () => {
        throw new TypeError("offline");
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 0,
    );
});

test("suggestMove preserves AbortError instead of wrapping it", async () => {
    const fetchImpl = async () => {
        throw new DOMException("The operation was aborted.", "AbortError");
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
});

test("suggestMove maps a non-AbortError to AbortError when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = async () => {
        throw new TypeError("Failed to fetch");
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl, signal: controller.signal }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
});

test("suggestMove treats HTTP 499 as AbortError", async () => {
    const fetchImpl = async () => ({ ok: false, status: 499, async json() { return {}; } });

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
});

test("suggestMove treats a resolved response as AbortError when the signal is aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = async () => ({
        ok: true,
        status: 200,
        async json() {
            return { move: "left", mode: "llm", source: "llm", reason: "late" };
        },
    });

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl, signal: controller.signal }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
});

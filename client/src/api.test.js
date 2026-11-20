import assert from "node:assert/strict";
import test from "node:test";
import { suggestMove, SuggestError } from "./api.js";

const BOARD = [
    [2, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 2],
];

const TRACEPARENT_RE = /^00-[0-9a-f]{32}-[0-9a-f]{16}-01$/;

test("suggestMove posts the board and mode with traceparent, then returns the body", async () => {
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
    assert.match(calls[0].options.headers.traceparent, TRACEPARENT_RE);
    assert.deepEqual(JSON.parse(calls[0].options.body), { board: BOARD, mode: "llm" });
    assert.deepEqual(body, { move: "left", mode: "llm", source: "llm", reason: "Merges." });
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

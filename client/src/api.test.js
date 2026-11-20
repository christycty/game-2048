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

function collectCalls() {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: true,
            async json() {
                return { move: "left", mode: "llm", source: "llm", reason: "Merges." };
            },
        };
    };
    return { calls, fetchImpl };
}

test("suggestMove posts the board and mode with traceparent, then returns the body", async () => {
    const { calls, fetchImpl } = collectCalls();

    const body = await suggestMove(BOARD, "llm", { fetch: fetchImpl });

    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/suggest");
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.match(calls[0].options.headers.traceparent, TRACEPARENT_RE);
    assert.deepEqual(JSON.parse(calls[0].options.body), { board: BOARD, mode: "llm" });
    assert.deepEqual(body, { move: "left", mode: "llm", source: "llm", reason: "Merges." });
});

test("suggestMove beacons rate_limit on 429 and does not on success", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return { ok: false, status: 429, async json() { return {}; } };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 429,
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.equal(beacon.options.method, "POST");
    assert.equal(beacon.options.keepalive, true);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "rate_limit" });
});

test("suggestMove beacons fail on non-429 HTTP errors", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return { ok: false, status: 409, async json() { return {}; } };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 409,
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "fail" });
});

test("suggestMove beacons fail on network failure", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        throw new TypeError("offline");
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 0,
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "fail" });
});

test("suggestMove ignores beacon failures", async () => {
    const fetchImpl = async (url) => {
        if (url.endsWith("/client-events")) {
            throw new TypeError("beacon down");
        }
        return { ok: false, status: 500, async json() { return {}; } };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.status === 500,
    );
});

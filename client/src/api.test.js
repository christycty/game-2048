import assert from "node:assert/strict";
import test from "node:test";
import {
    suggestMove,
    SuggestError,
    isAbortError,
    classifySuggestLimit,
    LIMIT_CAPACITY,
    LIMIT_SPEND,
    DETAIL_MODEL_BUSY,
    DETAIL_SPEND_CAP,
} from "./api.js";

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
    assert.equal(
        calls.some((c) => c.url === "/client-events"),
        false,
        "success must not beacon fail/rate_limit",
    );
    assert.equal(calls[0].options.method, "POST");
    assert.equal(calls[0].options.headers["Content-Type"], "application/json");
    assert.match(calls[0].options.headers.traceparent, TRACEPARENT_RE);
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

test("classifySuggestLimit prefers header then detail; unknown is spend", () => {
    assert.equal(classifySuggestLimit(DETAIL_MODEL_BUSY, null), LIMIT_CAPACITY);
    assert.equal(classifySuggestLimit(DETAIL_SPEND_CAP, "capacity"), LIMIT_CAPACITY);
    assert.equal(classifySuggestLimit(DETAIL_SPEND_CAP, "spend"), LIMIT_SPEND);
    assert.equal(classifySuggestLimit(null, null), LIMIT_SPEND);
});

test("suggestMove beacons rate_limit on spend 429", async () => {
    const calls = [];
    const headers = new Headers({
        "retry-after": "60",
        "x-suggest-limit": "spend",
    });
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: false,
            status: 429,
            headers,
            async json() {
                return { detail: DETAIL_SPEND_CAP };
            },
        };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) =>
            error instanceof SuggestError &&
            error.status === 429 &&
            error.limitReason === LIMIT_SPEND &&
            error.retryAfter === 60,
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.equal(beacon.options.method, "POST");
    assert.equal(beacon.options.keepalive, true);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "rate_limit" });
});

test("suggestMove beacons model_busy on capacity 429", async () => {
    const calls = [];
    const headers = new Headers({
        "retry-after": "1",
        "x-suggest-limit": "capacity",
    });
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: false,
            status: 429,
            headers,
            async json() {
                return { detail: DETAIL_MODEL_BUSY };
            },
        };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) =>
            error instanceof SuggestError &&
            error.status === 429 &&
            error.limitReason === LIMIT_CAPACITY &&
            error.retryAfter === 1,
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "model_busy" });
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

test("suggestMove beacons fail when response JSON cannot be parsed", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: true,
            status: 200,
            async json() {
                throw new SyntaxError("Unexpected end of JSON input");
            },
        };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.message.includes("unusable"),
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "fail" });
});

test("suggestMove beacons fail when response body lacks a move", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return { ok: true, status: 200, async json() { return { reason: "nope" }; } };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => error instanceof SuggestError && error.message.includes("unusable"),
    );

    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "fail" });
});

test("suggestMove skips beacons when shouldReportOutcome is false", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: false,
            status: 429,
            headers: new Headers({ "retry-after": "1" }),
            async json() {
                return { detail: DETAIL_SPEND_CAP };
            },
        };
    };

    await assert.rejects(
        () =>
            suggestMove(BOARD, "llm", {
                fetch: fetchImpl,
                shouldReportOutcome: () => false,
            }),
        (error) => error instanceof SuggestError && error.status === 429,
    );

    assert.equal(
        calls.some((c) => c.url === "/client-events"),
        false,
    );
});

test("suggestMove re-checks shouldReportOutcome after the suggest await", async () => {
    // Must not capture a boolean at call start — abandon can flip mid-flight.
    let abandoned = false;
    let releaseSuggest;
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        await new Promise((resolve) => {
            releaseSuggest = resolve;
        });
        return {
            ok: false,
            status: 429,
            headers: new Headers({ "retry-after": "1" }),
            async json() {
                return { detail: DETAIL_MODEL_BUSY };
            },
        };
    };

    const pending = suggestMove(BOARD, "llm", {
        fetch: fetchImpl,
        shouldReportOutcome: () => !abandoned,
    });
    abandoned = true;
    releaseSuggest();

    await assert.rejects(
        () => pending,
        (error) => error instanceof SuggestError && error.status === 429,
    );
    assert.equal(
        calls.some((c) => c.url === "/client-events"),
        false,
    );
});

test("suggestMove treats abort during json of a bad body as AbortError and beacons cancel", async () => {
    // Abort across await response.json() must not beacon fail for an unusable body.
    const controller = new AbortController();
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: true,
            status: 200,
            async json() {
                controller.abort();
                return { reason: "nope" };
            },
        };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl, signal: controller.signal }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "cancel" });
});

test("suggestMove preserves AbortError and beacons cancel", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        throw new DOMException("The operation was aborted.", "AbortError");
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.equal(beacon.options.keepalive, true);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "cancel" });
});

test("suggestMove maps a non-AbortError to AbortError when the signal is already aborted and beacons cancel", async () => {
    const calls = [];
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        throw new TypeError("Failed to fetch");
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl, signal: controller.signal }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "cancel" });
});

test("suggestMove treats HTTP 499 as AbortError and beacons cancel", async () => {
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return { ok: false, status: 499, async json() { return {}; } };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "cancel" });
});

test("suggestMove treats a resolved response as AbortError when the signal is aborted and beacons cancel", async () => {
    const calls = [];
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        return {
            ok: true,
            status: 200,
            async json() {
                return { move: "left", mode: "llm", source: "llm", reason: "late" };
            },
        };
    };

    await assert.rejects(
        () => suggestMove(BOARD, "llm", { fetch: fetchImpl, signal: controller.signal }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "cancel" });
});

test("suggestMove abort still beacons cancel when shouldReportOutcome is false", async () => {
    // Stop/move bumps the token before fetch rejects; cancel must still count.
    const calls = [];
    const fetchImpl = async (url, options) => {
        calls.push({ url, options });
        if (url.endsWith("/client-events")) {
            return { ok: true, status: 204, async json() { return {}; } };
        }
        throw new DOMException("The operation was aborted.", "AbortError");
    };

    await assert.rejects(
        () =>
            suggestMove(BOARD, "llm", {
                fetch: fetchImpl,
                shouldReportOutcome: () => false,
            }),
        (error) => isAbortError(error) && !(error instanceof SuggestError),
    );
    const beacon = calls.find((c) => c.url === "/client-events");
    assert.ok(beacon);
    assert.deepEqual(JSON.parse(beacon.options.body), { outcome: "cancel" });
});

import assert from "node:assert/strict";
import test from "node:test";
import { createTraceparent } from "./trace.js";

const TRACEPARENT_RE = /^00-([0-9a-f]{32})-([0-9a-f]{16})-01$/;

test("createTraceparent returns a sampled W3C traceparent", () => {
    const header = createTraceparent();
    const match = TRACEPARENT_RE.exec(header);
    assert.ok(match, header);
    assert.notEqual(match[1], "0".repeat(32));
    assert.notEqual(match[2], "0".repeat(16));
});

test("createTraceparent retries when getRandomValues returns all zeros", () => {
    const original = crypto.getRandomValues.bind(crypto);
    let calls = 0;
    let seenZero16 = false;
    let seenZero8 = false;
    crypto.getRandomValues = (bytes) => {
        calls += 1;
        if (bytes.length === 16 && !seenZero16) {
            seenZero16 = true;
            bytes.fill(0);
            return bytes;
        }
        if (bytes.length === 8 && !seenZero8) {
            seenZero8 = true;
            bytes.fill(0);
            return bytes;
        }
        return original(bytes);
    };
    try {
        const header = createTraceparent();
        const match = TRACEPARENT_RE.exec(header);
        assert.ok(match, header);
        assert.notEqual(match[1], "0".repeat(32));
        assert.notEqual(match[2], "0".repeat(16));
        // Two ids (trace + span); each rejects one all-zero draw then succeeds.
        assert.equal(calls, 4);
    } finally {
        crypto.getRandomValues = original;
    }
});

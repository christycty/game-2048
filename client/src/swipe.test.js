import assert from "node:assert/strict";
import test from "node:test";
import { SWIPE_THRESHOLD, swipeDirection } from "./swipe.js";

test("a short drag is not a swipe", () => {
    // Distances are in pixels; just under the shared threshold is not a swipe.
    assert.equal(swipeDirection(10, 0), null);
    assert.equal(swipeDirection(0, -(SWIPE_THRESHOLD - 1)), null);
});

test("the longer axis chooses the swipe direction", () => {
    assert.equal(swipeDirection(-80, 10), "left");
    assert.equal(swipeDirection(80, -10), "right");
    assert.equal(swipeDirection(10, 80), "down");
    assert.equal(swipeDirection(-10, -80), "up");
});

test("a diagonal drag follows the vertical axis when the distances match", () => {
    // Both axes travel the same distance, so the vertical one wins.
    assert.equal(swipeDirection(40, 40), "down");
    assert.equal(swipeDirection(-40, -40), "up");
});

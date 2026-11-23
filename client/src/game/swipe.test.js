import assert from "node:assert/strict";
import test from "node:test";
import { SWIPE_THRESHOLD, swipeDirection } from "./swipe.js";

test("a short drag is not a swipe", () => {
    // Distances are in pixels; just under the shared threshold is not a swipe.
    assert.equal(swipeDirection(0, 0), null);
    assert.equal(swipeDirection(SWIPE_THRESHOLD - 1, 0), null);
    assert.equal(swipeDirection(-(SWIPE_THRESHOLD - 1), 0), null);
    assert.equal(swipeDirection(0, SWIPE_THRESHOLD - 1), null);
    assert.equal(swipeDirection(0, -(SWIPE_THRESHOLD - 1)), null);
    assert.equal(swipeDirection(SWIPE_THRESHOLD - 1, SWIPE_THRESHOLD - 1), null);
});

test("a drag at the exact threshold counts in each direction", () => {
    assert.equal(swipeDirection(SWIPE_THRESHOLD, 0), "right");
    assert.equal(swipeDirection(-SWIPE_THRESHOLD, 0), "left");
    assert.equal(swipeDirection(0, SWIPE_THRESHOLD), "down");
    assert.equal(swipeDirection(0, -SWIPE_THRESHOLD), "up");
});

test("the longer axis chooses the swipe direction", () => {
    const short = SWIPE_THRESHOLD - 1;
    const long = SWIPE_THRESHOLD * 2;
    assert.equal(swipeDirection(-long, short), "left");
    assert.equal(swipeDirection(long, -short), "right");
    assert.equal(swipeDirection(short, long), "down");
    assert.equal(swipeDirection(-short, -long), "up");
});

test("a diagonal drag follows the vertical axis when the distances match", () => {
    // Both axes travel the same distance, so the vertical one wins.
    assert.equal(swipeDirection(SWIPE_THRESHOLD, SWIPE_THRESHOLD), "down");
    assert.equal(swipeDirection(-SWIPE_THRESHOLD, -SWIPE_THRESHOLD), "up");
});

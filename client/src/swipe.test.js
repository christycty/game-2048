import assert from "node:assert/strict";
import test from "node:test";
import { swipeDirection } from "./swipe.js";

test("a short drag is not a swipe", () => {
    assert.equal(swipeDirection(10, 0), null);
    assert.equal(swipeDirection(0, -23), null);
});

test("the longer axis chooses the swipe direction", () => {
    assert.equal(swipeDirection(-80, 10), "left");
    assert.equal(swipeDirection(80, -10), "right");
    assert.equal(swipeDirection(10, 80), "down");
    assert.equal(swipeDirection(-10, -80), "up");
});

test("a diagonal drag follows the vertical axis when the distances match", () => {
    assert.equal(swipeDirection(40, 40), "down");
    assert.equal(swipeDirection(-40, -40), "up");
});

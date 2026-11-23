import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
    capitalize,
    formatSuggestionHint,
    hintForSuggestFailure,
    isRetryingHint,
    HINT_CAPACITY_BUSY,
    HINT_CAPACITY_RETRYING,
    HINT_SPEND_CAP,
    HINT_SUGGEST_FAILED,
    HINT_SUGGEST_RETRYING,
} from "./suggestHints.js";

describe("capitalize", () => {
    it("uppercases the first character", () => {
        assert.equal(capitalize("left"), "Left");
    });
});

describe("formatSuggestionHint", () => {
    it("includes a trimmed reason when present", () => {
        assert.equal(formatSuggestionHint("up", "  score line  "), "Suggested: Up. score line");
    });

    it("omits the reason clause when empty or missing", () => {
        assert.equal(formatSuggestionHint("down", "   "), "Suggested: Down.");
        assert.equal(formatSuggestionHint("left", null), "Suggested: Left.");
    });
});

describe("hintForSuggestFailure", () => {
    it("uses capacity retry copy when retrying a non-model-miss failure", () => {
        assert.equal(
            hintForSuggestFailure({ isCapacityBusy: true, isSpendCap: false, retrying: true }),
            HINT_CAPACITY_RETRYING,
        );
        assert.equal(
            hintForSuggestFailure({
                isCapacityBusy: false,
                isSpendCap: false,
                isModelMiss: false,
                retrying: true,
            }),
            HINT_CAPACITY_RETRYING,
        );
    });

    it("uses model-miss retry copy while Auto Play is retrying a fallback", () => {
        assert.equal(
            hintForSuggestFailure({
                isCapacityBusy: false,
                isSpendCap: false,
                isModelMiss: true,
                retrying: true,
            }),
            HINT_SUGGEST_RETRYING,
        );
    });

    it("uses capacity, spend, or generic stop copy", () => {
        assert.equal(
            hintForSuggestFailure({ isCapacityBusy: true, isSpendCap: false, retrying: false }),
            HINT_CAPACITY_BUSY,
        );
        assert.equal(
            hintForSuggestFailure({ isCapacityBusy: false, isSpendCap: true, retrying: false }),
            HINT_SPEND_CAP,
        );
        assert.equal(
            hintForSuggestFailure({ isCapacityBusy: false, isSpendCap: false, retrying: false }),
            HINT_SUGGEST_FAILED,
        );
    });
});

describe("isRetryingHint", () => {
    it("matches only transient retrying status strings", () => {
        assert.equal(isRetryingHint(HINT_CAPACITY_RETRYING), true);
        assert.equal(isRetryingHint(HINT_SUGGEST_RETRYING), true);
        assert.equal(isRetryingHint(HINT_CAPACITY_BUSY), false);
        assert.equal(isRetryingHint(HINT_SUGGEST_FAILED), false);
        assert.equal(isRetryingHint("Suggested: Right. ok"), false);
        assert.equal(isRetryingHint(null), false);
    });
});

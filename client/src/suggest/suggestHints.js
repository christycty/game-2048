/** Pure hint copy + formatting for suggest / Auto Play outcomes. Keep policy in App/hooks. */

export const HINT_SUGGEST_FAILED = "AI could not suggest a move";
export const HINT_CAPACITY_RETRYING = "Model busy. Retrying…";
export const HINT_CAPACITY_BUSY = "Model busy. Wait a moment and try again.";
export const HINT_SPEND_CAP = "Too many suggestions. Wait a moment and try again.";

export function capitalize(value) {
    return value.charAt(0).toUpperCase() + value.slice(1);
}

export function formatSuggestionHint(move, reason) {
    const trimmed = typeof reason === "string" ? reason.trim() : "";
    return trimmed
        ? `Suggested: ${capitalize(move)}. ${trimmed}`
        : `Suggested: ${capitalize(move)}.`;
}

/** Map a classified suggest failure to status copy (capacity retry vs stop). */
export function hintForSuggestFailure({ isCapacityBusy, isSpendCap, retrying }) {
    if (retrying) return HINT_CAPACITY_RETRYING;
    if (isCapacityBusy) return HINT_CAPACITY_BUSY;
    if (isSpendCap) return HINT_SPEND_CAP;
    return HINT_SUGGEST_FAILED;
}

/** Pure hint copy + formatting for suggest / Auto Play outcomes. Keep policy in App/hooks. */

// Model miss / transport: invite a later retry (Auto Play may retry first).
export const HINT_SUGGEST_FAILED =
    "AI could not suggest a move. Try again in a moment.";
export const HINT_SUGGEST_RETRYING = "AI could not suggest a move. Retrying…";
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

export function isRetryingHint(hint) {
    return hint === HINT_CAPACITY_RETRYING || hint === HINT_SUGGEST_RETRYING;
}

/** Map a classified suggest failure to status copy (capacity / spend / model miss). */
export function hintForSuggestFailure({
    isCapacityBusy,
    isSpendCap,
    isModelMiss = false,
    retrying,
}) {
    if (retrying) {
        return isModelMiss ? HINT_SUGGEST_RETRYING : HINT_CAPACITY_RETRYING;
    }
    if (isCapacityBusy) return HINT_CAPACITY_BUSY;
    if (isSpendCap) return HINT_SPEND_CAP;
    return HINT_SUGGEST_FAILED;
}

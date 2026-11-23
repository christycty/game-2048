import { useRef, useState } from "react";
import { suggestMove, SuggestError, isAbortError, LIMIT_CAPACITY } from "../suggest/api";
import { AUTO_PLAY_CAPACITY_MAX_RETRIES, hasMoves, tilesToBoard } from "../game/game";
import {
    formatSuggestionHint,
    hintForSuggestFailure,
    HINT_SUGGEST_FAILED,
} from "../suggest/suggestHints";

/**
 * Suggest token, AbortController, capacity retries, and beacon gating.
 * Cross-calls stopAutoPlay / handleMove via the refs passed in (assigned after render).
 */
export function useSuggestSession({
    animatingRef,
    lostRef,
    wonRef,
    tilesRef,
    autoPlayingRef,
    autoApplyingRef,
    aiModeRef,
    setBusy,
    setPendingMove,
    setHint,
    clearSuggestion,
    stopAutoPlayRef,
    handleMoveRef,
}) {
    const [suggesting, setSuggesting] = useState(false);
    const suggestingRef = useRef(false);
    const suggestTokenRef = useRef(0);
    const suggestAbortRef = useRef(null);
    const capacityRetriesRef = useRef(0);

    function resetCapacityRetries() {
        capacityRetriesRef.current = 0;
    }

    // Abort the fetch and drop the token so a late response cannot land.
    // Busy/suggesting cleanup is owned by the caller (Stop vs move vs New Game).
    function abortInFlightSuggest() {
        suggestAbortRef.current?.abort();
        suggestAbortRef.current = null;
        if (!suggestingRef.current) return;
        suggestTokenRef.current += 1;
        suggestingRef.current = false;
        setSuggesting(false);
    }

    async function handleSuggest() {
        if (animatingRef.current || lostRef.current || wonRef.current || suggestingRef.current) return;
        if (!hasMoves(tilesRef.current)) {
            stopAutoPlayRef.current();
            if (!animatingRef.current) setBusy(false);
            return;
        }

        const token = suggestTokenRef.current + 1;
        suggestTokenRef.current = token;
        const controller = new AbortController();
        suggestAbortRef.current = controller;
        suggestingRef.current = true;
        setSuggesting(true);
        setBusy(true);
        // Auto Play keeps the last hint through Thinking; a fresh AI ask clears both.
        if (autoPlayingRef.current) {
            setPendingMove(null);
        } else {
            clearSuggestion();
        }

        let scheduleCapacityRetry = false;
        let capacityRetryDelayMs = 1000;
        try {
            const suggestion = await suggestMove(tilesToBoard(tilesRef.current), aiModeRef.current, {
                signal: controller.signal,
                // Stale-token ignores must not beacon fail/rate_limit/model_busy; abort beacons cancel.
                shouldReportOutcome: () => suggestTokenRef.current === token,
            });
            if (suggestTokenRef.current !== token) return;
            resetCapacityRetries();
            // "fallback" is a fixed move order, not a model choice.
            if (suggestion.source === "fallback") {
                setHint(HINT_SUGGEST_FAILED);
                stopAutoPlayRef.current();
                return;
            }
            const hintText = formatSuggestionHint(suggestion.move, suggestion.reason);

            if (autoPlayingRef.current) {
                setHint(hintText);
                suggestingRef.current = false;
                setSuggesting(false);
                autoApplyingRef.current = true;
                const moved = handleMoveRef.current(suggestion.move);
                autoApplyingRef.current = false;
                if (!moved) {
                    setHint(HINT_SUGGEST_FAILED);
                    stopAutoPlayRef.current();
                    if (!animatingRef.current) setBusy(false);
                }
                return;
            }

            setPendingMove(suggestion.move);
            setHint(hintText);
        } catch (error) {
            // Stale after local abort/supersede: caller already owns Auto Play / busy cleanup.
            if (suggestTokenRef.current !== token) return;
            // Token-matched abort (e.g. HTTP 499 without a local abort): stay silent but end the loop.
            if (isAbortError(error)) {
                stopAutoPlayRef.current();
                return;
            }
            setPendingMove(null);
            const isCapacityBusy =
                error instanceof SuggestError &&
                error.status === 429 &&
                error.limitReason === LIMIT_CAPACITY;
            const isSpendCap =
                error instanceof SuggestError &&
                error.status === 429 &&
                !isCapacityBusy;

            if (
                isCapacityBusy &&
                autoPlayingRef.current &&
                capacityRetriesRef.current < AUTO_PLAY_CAPACITY_MAX_RETRIES
            ) {
                capacityRetriesRef.current += 1;
                capacityRetryDelayMs = Math.max(1, error.retryAfter ?? 1) * 1000;
                setHint(hintForSuggestFailure({ isCapacityBusy, isSpendCap, retrying: true }));
                scheduleCapacityRetry = true;
                return;
            }

            setHint(hintForSuggestFailure({ isCapacityBusy, isSpendCap, retrying: false }));
            stopAutoPlayRef.current();
        } finally {
            if (suggestAbortRef.current === controller) {
                suggestAbortRef.current = null;
            }
            if (suggestTokenRef.current === token) {
                suggestingRef.current = false;
                setSuggesting(false);
                if (scheduleCapacityRetry) {
                    // Keep busy through the Retry-After wait (same idea as AUTO_PLAY_GAP_MS).
                    window.setTimeout(() => {
                        if (suggestTokenRef.current !== token) return;
                        if (!autoPlayingRef.current) {
                            if (!animatingRef.current) setBusy(false);
                            return;
                        }
                        void handleSuggest();
                    }, capacityRetryDelayMs);
                } else if (!animatingRef.current) {
                    setBusy(false);
                }
            }
        }
    }

    return {
        suggesting,
        setSuggesting,
        suggestingRef,
        suggestTokenRef,
        suggestAbortRef,
        abortInFlightSuggest,
        resetCapacityRetries,
        handleSuggest,
    };
}

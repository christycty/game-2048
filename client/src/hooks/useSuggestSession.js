import { useEffect, useRef, useState } from "react";
import { suggestMove, SuggestError, isAbortError, LIMIT_CAPACITY } from "../suggest/api";
import {
    AUTO_PLAY_CAPACITY_MAX_RETRIES,
    AUTO_PLAY_FALLBACK_MAX_RETRIES,
    AUTO_PLAY_FALLBACK_RETRY_MS,
    hasMoves,
    tilesToBoard,
} from "../game/game";
import {
    formatSuggestionHint,
    hintForSuggestFailure,
    HINT_SUGGEST_FAILED,
} from "../suggest/suggestHints";

/**
 * Suggest token, AbortController, Auto Play retries (capacity + model miss), beacon gating.
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
    const retryTimerRef = useRef(null);
    const capacityRetriesRef = useRef(0);
    const fallbackRetriesRef = useRef(0);

    function clearRetryTimer() {
        if (retryTimerRef.current !== null) {
            window.clearTimeout(retryTimerRef.current);
            retryTimerRef.current = null;
        }
    }

    function resetCapacityRetries() {
        clearRetryTimer();
        capacityRetriesRef.current = 0;
        fallbackRetriesRef.current = 0;
    }

    // Abort the fetch (or pending retry wait) and drop the token so a late response cannot land.
    // Busy/suggesting cleanup is owned by the caller (Stop vs move vs New Game).
    function abortInFlightSuggest() {
        const hadPendingRetry = retryTimerRef.current !== null;
        clearRetryTimer();
        const controller = suggestAbortRef.current;
        suggestAbortRef.current = null;
        if (suggestingRef.current || hadPendingRetry) {
            suggestTokenRef.current += 1;
            suggestingRef.current = false;
            setSuggesting(false);
        }
        controller?.abort();
    }

    function resetSuggestSession() {
        clearRetryTimer();
        const controller = suggestAbortRef.current;
        suggestAbortRef.current = null;
        suggestTokenRef.current += 1;
        suggestingRef.current = false;
        setSuggesting(false);
        resetCapacityRetries();
        controller?.abort();
    }

    useEffect(
        () => () => {
            clearRetryTimer();
            const controller = suggestAbortRef.current;
            suggestAbortRef.current = null;
            // Match Stop/move/New Game: drop the token so a late resolve cannot land.
            suggestTokenRef.current += 1;
            suggestingRef.current = false;
            controller?.abort();
        },
        [],
    );

    async function handleSuggest() {
        if (animatingRef.current || lostRef.current || wonRef.current || suggestingRef.current) return;
        if (!hasMoves(tilesRef.current)) {
            stopAutoPlayRef.current();
            if (!animatingRef.current) setBusy(false);
            return;
        }

        clearRetryTimer();
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

        let scheduleRetry = false;
        let retryDelayMs = 1000;
        try {
            const suggestion = await suggestMove(tilesToBoard(tilesRef.current), aiModeRef.current, {
                signal: controller.signal,
                // Stale-token ignores must not beacon fail/rate_limit/model_busy; abort beacons cancel.
                shouldReportOutcome: () => suggestTokenRef.current === token,
            });
            if (suggestTokenRef.current !== token) return;
            // "fallback" is a fixed move order, not a model choice — treat as model miss.
            if (suggestion.source === "fallback") {
                if (
                    autoPlayingRef.current &&
                    fallbackRetriesRef.current < AUTO_PLAY_FALLBACK_MAX_RETRIES
                ) {
                    fallbackRetriesRef.current += 1;
                    retryDelayMs = AUTO_PLAY_FALLBACK_RETRY_MS;
                    setHint(
                        hintForSuggestFailure({
                            isCapacityBusy: false,
                            isSpendCap: false,
                            isModelMiss: true,
                            retrying: true,
                        }),
                    );
                    scheduleRetry = true;
                    return;
                }
                setHint(
                    hintForSuggestFailure({
                        isCapacityBusy: false,
                        isSpendCap: false,
                        isModelMiss: true,
                        retrying: false,
                    }),
                );
                stopAutoPlayRef.current();
                return;
            }
            resetCapacityRetries();
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
                retryDelayMs = Math.max(1, error.retryAfter ?? 1) * 1000;
                setHint(hintForSuggestFailure({ isCapacityBusy, isSpendCap, retrying: true }));
                scheduleRetry = true;
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
                if (scheduleRetry) {
                    // Keep busy through the wait (same idea as AUTO_PLAY_GAP_MS).
                    clearRetryTimer();
                    retryTimerRef.current = window.setTimeout(() => {
                        retryTimerRef.current = null;
                        if (suggestTokenRef.current !== token) return;
                        if (!autoPlayingRef.current) {
                            if (!animatingRef.current) setBusy(false);
                            return;
                        }
                        void handleSuggest();
                    }, retryDelayMs);
                } else if (!animatingRef.current) {
                    setBusy(false);
                }
            }
        }
    }

    return {
        suggesting,
        suggestingRef,
        abortInFlightSuggest,
        resetCapacityRetries,
        resetSuggestSession,
        handleSuggest,
    };
}

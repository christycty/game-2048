import { useEffect, useState } from "react";
import { hasMoves } from "../game/game";
import { HINT_SUGGEST_FAILED, isRetryingHint } from "../suggest/suggestHints";

/**
 * Auto Play toggle/stop and autoApplyingRef.
 * Shared failed-apply exit: hint + stop + busy release (anti-pattern #8).
 * Stop releases busy when idle (anti-pattern #7).
 */
export function useAutoPlayController({
    animatingRef,
    suggestingRef,
    autoPlayingRef,
    autoApplyingRef,
    lostRef,
    wonRef,
    tilesRef,
    pendingMove,
    setBusy,
    setPendingMove,
    setHint,
    abortInFlightSuggest,
    resetCapacityRetries,
    clearGapTimer,
    handleMove,
    handleSuggest,
}) {
    const [autoPlaying, setAutoPlaying] = useState(false);

    function resetAutoPlay() {
        autoPlayingRef.current = false;
        autoApplyingRef.current = false;
        setAutoPlaying(false);
    }

    useEffect(
        () => () => {
            autoPlayingRef.current = false;
            autoApplyingRef.current = false;
        },
        [autoPlayingRef, autoApplyingRef],
    );

    function stopAutoPlay() {
        if (!autoPlayingRef.current) return;
        autoPlayingRef.current = false;
        setAutoPlaying(false);
        clearGapTimer();
        resetCapacityRetries();
        // Stopping cancels any scheduled retry, so transient "… Retrying…" copy must not linger.
        setHint((current) => (isRetryingHint(current) ? null : current));
        // The post-settle gap keeps busy true so AI stays inactive through the pause.
        // Stopping must release that hold when nothing else is in flight.
        if (!animatingRef.current && !suggestingRef.current) {
            setBusy(false);
        }
    }

    function handleAutoPlayToggle() {
        if (autoPlayingRef.current) {
            // Stop during Thinking or retry backoff cancels the active suggest session.
            if (abortInFlightSuggest() && !animatingRef.current) {
                setBusy(false);
            }
            stopAutoPlay();
            return;
        }
        if (lostRef.current || wonRef.current || animatingRef.current || suggestingRef.current) return;
        if (!pendingMove && !hasMoves(tilesRef.current)) return;

        autoPlayingRef.current = true;
        setAutoPlaying(true);

        if (pendingMove) {
            autoApplyingRef.current = true;
            const moved = handleMove(pendingMove);
            autoApplyingRef.current = false;
            if (!moved) {
                setPendingMove(null);
                setHint(HINT_SUGGEST_FAILED);
                stopAutoPlay();
            }
            return;
        }
        void handleSuggest();
    }

    return {
        autoPlaying,
        stopAutoPlay,
        resetAutoPlay,
        handleAutoPlayToggle,
    };
}

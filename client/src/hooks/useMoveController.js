import { useEffect, useRef } from "react";
import { applyMove, AUTO_PLAY_GAP_MS, SETTLE_MS } from "../game/game";

/**
 * Board moves, settle timer, and Auto Play gap → suggest.
 * Continues the loop via handleSuggestRef (assigned after render).
 */
export function useMoveController({
    tilesRef,
    scoreRef,
    lostRef,
    wonRef,
    animatingRef,
    suggestingRef,
    autoPlayingRef,
    autoApplyingRef,
    setTiles,
    setCurrentScore,
    setBestScore,
    setLost,
    setWon,
    setBusy,
    setPendingMove,
    clearSuggestion,
    abortInFlightSuggest,
    stopAutoPlayRef,
    handleSuggestRef,
}) {
    const moveTokenRef = useRef(0);
    const settleTimerRef = useRef(null);
    const gapTimerRef = useRef(null);

    function clearGapTimer() {
        if (gapTimerRef.current !== null) {
            window.clearTimeout(gapTimerRef.current);
            gapTimerRef.current = null;
        }
    }

    function clearMoveTimers() {
        if (settleTimerRef.current !== null) {
            window.clearTimeout(settleTimerRef.current);
            settleTimerRef.current = null;
        }
        clearGapTimer();
    }

    function resetMoves(nextTiles) {
        moveTokenRef.current += 1;
        clearMoveTimers();
        animatingRef.current = false;
        tilesRef.current = nextTiles;
        scoreRef.current = 0;
        lostRef.current = false;
        wonRef.current = false;
        setTiles(nextTiles);
        setCurrentScore(0);
        setLost(false);
        setWon(false);
    }

    useEffect(
        () => () => {
            moveTokenRef.current += 1;
            clearMoveTimers();
            animatingRef.current = false;
        },
        [animatingRef],
    );

    function handleMove(direction) {
        if (animatingRef.current || lostRef.current || wonRef.current) return false;

        const result = applyMove(tilesRef.current, direction);
        if (!result.moved) {
            return false;
        }

        // A move that changes the board drops any in-flight suggestion or retry wait before stopping Auto Play so the suggest token is bumped.
        abortInFlightSuggest();

        // A manual move while auto-play is running takes control back.
        if (autoPlayingRef.current && !autoApplyingRef.current) {
            stopAutoPlayRef.current();
        }

        const token = moveTokenRef.current + 1;
        moveTokenRef.current = token;
        clearMoveTimers();
        animatingRef.current = true;
        setBusy(true);
        // Auto-play keeps the latest hint visible while the move slides.
        if (autoApplyingRef.current) {
            setPendingMove(null);
        } else {
            clearSuggestion();
        }
        setTiles(result.visualTiles);

        settleTimerRef.current = window.setTimeout(() => {
            settleTimerRef.current = null;
            if (moveTokenRef.current !== token) return;
            const nextScore = scoreRef.current + result.scoreGained;
            tilesRef.current = result.resolvedTiles;
            scoreRef.current = nextScore;
            lostRef.current = Boolean(result.lost);
            wonRef.current = Boolean(result.won);
            setTiles(result.resolvedTiles);
            setCurrentScore(nextScore);
            setBestScore((best) => Math.max(best, nextScore));
            animatingRef.current = false;
            if (result.won || result.lost) {
                setWon(Boolean(result.won));
                setLost(Boolean(result.lost));
                setBusy(false);
                clearSuggestion();
                stopAutoPlayRef.current();
                return;
            }
            if (autoPlayingRef.current) {
                // Keep busy through the gap. Stop releases busy when idle; New Game bumps the token.
                clearGapTimer();
                gapTimerRef.current = window.setTimeout(() => {
                    gapTimerRef.current = null;
                    if (moveTokenRef.current !== token) return;
                    if (!autoPlayingRef.current) {
                        if (!suggestingRef.current) setBusy(false);
                        return;
                    }
                    void handleSuggestRef.current();
                }, AUTO_PLAY_GAP_MS);
                return;
            }
            setBusy(false);
        }, SETTLE_MS);
        return true;
    }

    return {
        handleMove,
        clearGapTimer,
        resetMoves,
    };
}

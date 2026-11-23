import { useRef } from "react";
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

    function handleMove(direction) {
        if (animatingRef.current || lostRef.current || wonRef.current) return false;

        const result = applyMove(tilesRef.current, direction);
        if (!result.moved) {
            // The board is unchanged, so an in-flight suggestion still applies.
            if (!suggestingRef.current) setBusy(false);
            return false;
        }

        // A manual move while auto-play is running takes control back.
        if (autoPlayingRef.current && !autoApplyingRef.current) {
            stopAutoPlayRef.current();
        }

        // A move that changes the board drops an in-flight suggestion so it cannot land on a stale board.
        if (suggestingRef.current) {
            abortInFlightSuggest();
        }

        const token = moveTokenRef.current + 1;
        moveTokenRef.current = token;
        animatingRef.current = true;
        setBusy(true);
        // Auto-play keeps the latest hint visible while the move slides.
        if (autoApplyingRef.current) {
            setPendingMove(null);
        } else {
            clearSuggestion();
        }
        setTiles(result.visualTiles);

        window.setTimeout(() => {
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
                stopAutoPlayRef.current();
                return;
            }
            if (autoPlayingRef.current) {
                // Keep busy through the gap. Stop releases busy when idle; New Game bumps the token.
                window.setTimeout(() => {
                    if (moveTokenRef.current !== token) return;
                    if (!autoPlayingRef.current) {
                        setBusy(false);
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
        moveTokenRef,
    };
}

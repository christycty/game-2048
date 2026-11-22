import { useEffect, useRef, useState } from "react";
import Board from "./components/Board";
import ScoreCard from "./components/ScoreCard";
import ActionPanel from "./components/ActionPanel";
import { suggestMove, SuggestError, isAbortError, LIMIT_CAPACITY } from "./api";
import {
    applyMove,
    AUTO_PLAY_CAPACITY_MAX_RETRIES,
    AUTO_PLAY_GAP_MS,
    createInitialTiles,
    hasMoves,
    SETTLE_MS,
    tilesToBoard,
} from "./game";
import {
    formatSuggestionHint,
    hintForSuggestFailure,
    HINT_SUGGEST_FAILED,
} from "./suggestHints";
import "./App.css";

const KEY_DIRECTIONS = {
    ArrowLeft: "left",
    ArrowRight: "right",
    ArrowUp: "up",
    ArrowDown: "down",
};

function App() {
    const [currentScore, setCurrentScore] = useState(0);
    const [bestScore, setBestScore] = useState(0);
    const [tiles, setTiles] = useState(createInitialTiles);
    const [lost, setLost] = useState(false);
    const [won, setWon] = useState(false);
    // Tracks a slide or an in-flight suggestion so the AI control can look inactive.
    const [busy, setBusy] = useState(false);
    const [suggesting, setSuggesting] = useState(false);
    const [autoPlaying, setAutoPlaying] = useState(false);
    const [aiMode, setAiMode] = useState("llm");
    const [pendingMove, setPendingMove] = useState(null);
    const [hint, setHint] = useState(null);

    // The key listener is bound once, so it reads the latest board and any in-flight suggestion from refs.
    const tilesRef = useRef(tiles);
    const scoreRef = useRef(0);
    const lostRef = useRef(false);
    const wonRef = useRef(false);
    const animatingRef = useRef(false);
    const suggestingRef = useRef(false);
    const autoPlayingRef = useRef(false);
    const autoApplyingRef = useRef(false);
    const moveTokenRef = useRef(0);
    const suggestTokenRef = useRef(0);
    const suggestAbortRef = useRef(null);
    const aiModeRef = useRef(aiMode);
    const capacityRetriesRef = useRef(0);

    function clearSuggestion() {
        setPendingMove(null);
        setHint(null);
    }

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

    function stopAutoPlay() {
        if (!autoPlayingRef.current) return;
        autoPlayingRef.current = false;
        setAutoPlaying(false);
        resetCapacityRetries();
        // The post-settle gap keeps busy true so AI stays inactive through the pause.
        // Stopping must release that hold when nothing else is in flight.
        if (!animatingRef.current && !suggestingRef.current) {
            setBusy(false);
        }
    }

    function startGame() {
        const nextTiles = createInitialTiles();
        moveTokenRef.current += 1;
        abortInFlightSuggest();
        suggestTokenRef.current += 1;
        animatingRef.current = false;
        suggestingRef.current = false;
        autoPlayingRef.current = false;
        autoApplyingRef.current = false;
        resetCapacityRetries();
        tilesRef.current = nextTiles;
        scoreRef.current = 0;
        lostRef.current = false;
        wonRef.current = false;
        setTiles(nextTiles);
        setCurrentScore(0);
        setLost(false);
        setWon(false);
        setBusy(false);
        setSuggesting(false);
        setAutoPlaying(false);
        clearSuggestion();
    }

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
            stopAutoPlay();
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
                stopAutoPlay();
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
                    void handleSuggest();
                }, AUTO_PLAY_GAP_MS);
                return;
            }
            setBusy(false);
        }, SETTLE_MS);
        return true;
    }

    async function handleSuggest() {
        if (animatingRef.current || lostRef.current || wonRef.current || suggestingRef.current) return;
        if (!hasMoves(tilesRef.current)) {
            stopAutoPlay();
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
                stopAutoPlay();
                return;
            }
            const hintText = formatSuggestionHint(suggestion.move, suggestion.reason);

            if (autoPlayingRef.current) {
                setHint(hintText);
                suggestingRef.current = false;
                setSuggesting(false);
                autoApplyingRef.current = true;
                const moved = handleMove(suggestion.move);
                autoApplyingRef.current = false;
                if (!moved) {
                    setHint(HINT_SUGGEST_FAILED);
                    stopAutoPlay();
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
                stopAutoPlay();
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
            stopAutoPlay();
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

    function handleApplySuggestion() {
        if (!pendingMove || animatingRef.current || lostRef.current || wonRef.current) return;
        handleMove(pendingMove);
    }

    function handleAutoPlayToggle() {
        if (autoPlayingRef.current) {
            // Stop during Thinking aborts the fetch so the server can cancel the run.
            if (suggestingRef.current) {
                abortInFlightSuggest();
                if (!animatingRef.current) setBusy(false);
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

    function handleModeChange(mode) {
        if (mode === aiModeRef.current) return;
        aiModeRef.current = mode;
        setAiMode(mode);
        // Previous mode's in-flight fetch or pending Play must not land.
        if (suggestingRef.current) {
            abortInFlightSuggest();
            if (!animatingRef.current) setBusy(false);
        }
        clearSuggestion();
    }

    useEffect(() => {
        function onKeyDown(event) {
            const direction = KEY_DIRECTIONS[event.key];
            if (!direction) return;
            event.preventDefault();
            handleMove(direction);
        }

        window.addEventListener("keydown", onKeyDown);
        return () => {
            window.removeEventListener("keydown", onKeyDown);
            suggestAbortRef.current?.abort();
            suggestAbortRef.current = null;
            // Match Stop/move/New Game: drop the token so a late resolve cannot land.
            suggestTokenRef.current += 1;
        };
    }, []);

    const canSuggest = !lost && !won && !busy && hasMoves(tiles);
    const canApplySuggestion = Boolean(pendingMove) && !lost && !won && !busy;
    const canToggleAutoPlay =
        autoPlaying || (!lost && !won && !busy && (Boolean(pendingMove) || hasMoves(tiles)));

    return (
        <div className="app">
            <ScoreCard score={currentScore} bestScore={bestScore}></ScoreCard>
            <Board tiles={tiles} lost={lost} won={won} onSwipe={handleMove}></Board>
            <ActionPanel
                onNewGame={startGame}
                onSuggest={handleSuggest}
                canSuggest={canSuggest && !autoPlaying}
                suggesting={suggesting}
                autoPlaying={autoPlaying}
                onAutoPlayToggle={handleAutoPlayToggle}
                canToggleAutoPlay={canToggleAutoPlay}
                mode={aiMode}
                onModeChange={handleModeChange}
                pendingMove={pendingMove}
                onApplySuggestion={handleApplySuggestion}
                canApplySuggestion={canApplySuggestion}
                hint={hint}
            ></ActionPanel>
        </div>
    );
}

export default App;

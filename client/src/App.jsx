import { useEffect, useRef, useState } from "react";
import Board from "./components/Board";
import ScoreCard from "./components/ScoreCard";
import ActionPanel from "./components/ActionPanel";
import { createInitialTiles, hasMoves } from "./game";
import { useAutoPlayController } from "./hooks/useAutoPlayController";
import { useKeyboardMoves } from "./hooks/useKeyboardMoves";
import { useMoveController } from "./hooks/useMoveController";
import { useSuggestSession } from "./hooks/useSuggestSession";
import "./App.css";

function App() {
    const [currentScore, setCurrentScore] = useState(0);
    const [bestScore, setBestScore] = useState(0);
    const [tiles, setTiles] = useState(createInitialTiles);
    const [lost, setLost] = useState(false);
    const [won, setWon] = useState(false);
    // Tracks a slide or an in-flight suggestion so the AI control can look inactive.
    const [busy, setBusy] = useState(false);
    const [aiMode, setAiMode] = useState("llm");
    const [pendingMove, setPendingMove] = useState(null);
    const [hint, setHint] = useState(null);

    // Shared refs: keyboard + async suggest/move/auto read these; hooks assign the cross-call slots.
    const tilesRef = useRef(tiles);
    const scoreRef = useRef(0);
    const lostRef = useRef(false);
    const wonRef = useRef(false);
    const animatingRef = useRef(false);
    const autoPlayingRef = useRef(false);
    const autoApplyingRef = useRef(false);
    const aiModeRef = useRef(aiMode);
    const stopAutoPlayRef = useRef(() => {});
    const handleMoveRef = useRef(() => false);
    const handleSuggestRef = useRef(async () => {});

    function clearSuggestion() {
        setPendingMove(null);
        setHint(null);
    }

    const {
        suggesting,
        setSuggesting,
        suggestingRef,
        suggestTokenRef,
        suggestAbortRef,
        abortInFlightSuggest,
        resetCapacityRetries,
        handleSuggest,
    } = useSuggestSession({
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
    });

    const { handleMove, moveTokenRef } = useMoveController({
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
    });

    const { autoPlaying, setAutoPlaying, stopAutoPlay, handleAutoPlayToggle } = useAutoPlayController({
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
        handleMove,
        handleSuggest,
    });

    useEffect(() => {
        stopAutoPlayRef.current = stopAutoPlay;
        handleMoveRef.current = handleMove;
        handleSuggestRef.current = handleSuggest;
    });

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

    function handleApplySuggestion() {
        if (!pendingMove || animatingRef.current || lostRef.current || wonRef.current) return;
        handleMove(pendingMove);
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

    useKeyboardMoves({
        onMove: handleMove,
        suggestAbortRef,
        suggestTokenRef,
    });

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

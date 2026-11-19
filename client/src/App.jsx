import { useEffect, useRef, useState } from "react";
import Board from "./components/Board";
import ScoreCard from "./components/ScoreCard";
import ActionPanel from "./components/ActionPanel";
import { suggestMove } from "./api";
import { applyMove, createInitialTiles, hasMoves, SETTLE_MS, tilesToBoard } from "./game";
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
    // Tracks a slide or an in-flight suggestion so the AI control can look inactive.
    const [busy, setBusy] = useState(false);
    const [suggesting, setSuggesting] = useState(false);
    const [aiMode, setAiMode] = useState("llm");
    const [pendingMove, setPendingMove] = useState(null);
    const [hint, setHint] = useState(null);

    // The key listener is bound once, so moves read the latest board from refs.
    const tilesRef = useRef(tiles);
    const scoreRef = useRef(0);
    const lostRef = useRef(false);
    const animatingRef = useRef(false);
    const suggestingRef = useRef(false);
    const moveTokenRef = useRef(0);
    const suggestTokenRef = useRef(0);
    const aiModeRef = useRef(aiMode);

    function clearSuggestion() {
        setPendingMove(null);
        setHint(null);
    }

    function startGame() {
        const nextTiles = createInitialTiles();
        moveTokenRef.current += 1;
        suggestTokenRef.current += 1;
        animatingRef.current = false;
        suggestingRef.current = false;
        tilesRef.current = nextTiles;
        scoreRef.current = 0;
        lostRef.current = false;
        setTiles(nextTiles);
        setCurrentScore(0);
        setLost(false);
        setBusy(false);
        setSuggesting(false);
        clearSuggestion();
    }

    function handleMove(direction) {
        if (animatingRef.current || lostRef.current) return false;

        // A key or swipe drops an in-flight suggestion so it cannot land on a stale board.
        if (suggestingRef.current) {
            suggestTokenRef.current += 1;
            suggestingRef.current = false;
            setSuggesting(false);
        }

        const result = applyMove(tilesRef.current, direction);
        if (!result.moved) {
            if (!animatingRef.current) setBusy(false);
            return false;
        }

        const token = moveTokenRef.current + 1;
        moveTokenRef.current = token;
        animatingRef.current = true;
        setBusy(true);
        clearSuggestion();
        setTiles(result.visualTiles);

        window.setTimeout(() => {
            if (moveTokenRef.current !== token) return;
            const nextScore = scoreRef.current + result.scoreGained;
            tilesRef.current = result.resolvedTiles;
            scoreRef.current = nextScore;
            lostRef.current = result.lost;
            setTiles(result.resolvedTiles);
            setCurrentScore(nextScore);
            setBestScore((best) => Math.max(best, nextScore));
            animatingRef.current = false;
            // A suggestion may still be waiting; keep the AI locked until it finishes.
            if (!suggestingRef.current) setBusy(false);
            if (result.lost) setLost(true);
        }, SETTLE_MS);
        return true;
    }

    async function handleSuggest() {
        if (animatingRef.current || lostRef.current || suggestingRef.current) return;
        if (!hasMoves(tilesRef.current)) return;

        const token = suggestTokenRef.current + 1;
        suggestTokenRef.current = token;
        suggestingRef.current = true;
        setSuggesting(true);
        setBusy(true);
        clearSuggestion();

        try {
            const suggestion = await suggestMove(tilesToBoard(tilesRef.current), aiModeRef.current);
            if (suggestTokenRef.current !== token) return;
            const reason =
                typeof suggestion.reason === "string" ? suggestion.reason.trim() : "";
            setPendingMove(suggestion.move);
            setHint(
                reason
                    ? `Suggested: ${capitalize(suggestion.move)}. ${reason}`
                    : `Suggested: ${capitalize(suggestion.move)}.`,
            );
        } catch {
            if (suggestTokenRef.current !== token) return;
            setPendingMove(null);
            setHint("AI could not suggest a move");
        } finally {
            if (suggestTokenRef.current === token) {
                suggestingRef.current = false;
                setSuggesting(false);
                if (!animatingRef.current) setBusy(false);
            }
        }
    }

    function handleApplySuggestion() {
        if (!pendingMove || animatingRef.current || lostRef.current) return;
        handleMove(pendingMove);
    }

    function handleModeChange(mode) {
        aiModeRef.current = mode;
        setAiMode(mode);
    }

    useEffect(() => {
        function onKeyDown(event) {
            const direction = KEY_DIRECTIONS[event.key];
            if (!direction) return;
            event.preventDefault();
            handleMove(direction);
        }

        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, []);

    const canSuggest = !lost && !busy && hasMoves(tiles);
    const canApplySuggestion = Boolean(pendingMove) && !lost && !busy;

    return (
        <div className="app">
            <ScoreCard score={currentScore} bestScore={bestScore}></ScoreCard>
            <Board tiles={tiles} lost={lost} onSwipe={handleMove}></Board>
            <ActionPanel
                onNewGame={startGame}
                onSuggest={handleSuggest}
                canSuggest={canSuggest}
                suggesting={suggesting}
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

function capitalize(value) {
    return value.charAt(0).toUpperCase() + value.slice(1);
}

export default App;

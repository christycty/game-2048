import { useEffect, useRef, useState } from "react";
import Board from "./components/Board";
import ScoreCard from "./components/ScoreCard";
import ActionPanel from "./components/ActionPanel";
import { applyMove, createInitialTiles, SLIDE_MS } from "./game";
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

  const tilesRef = useRef(tiles);
  const scoreRef = useRef(0);
  const lostRef = useRef(false);
  const animatingRef = useRef(false);
  const moveTokenRef = useRef(0);

  function startGame() {
    const nextTiles = createInitialTiles();
    moveTokenRef.current += 1;
    animatingRef.current = false;
    tilesRef.current = nextTiles;
    scoreRef.current = 0;
    lostRef.current = false;
    setTiles(nextTiles);
    setCurrentScore(0);
    setLost(false);
  }

  function handleMove(direction) {
    if (animatingRef.current || lostRef.current) return;

    const result = applyMove(tilesRef.current, direction);
    if (!result.moved) return;

    const token = moveTokenRef.current + 1;
    moveTokenRef.current = token;
    animatingRef.current = true;
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
      if (result.lost) setLost(true);
    }, SLIDE_MS + 20);
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

  return (
    <div className="app">
      <ScoreCard score={currentScore} bestScore={bestScore}></ScoreCard>
      <Board tiles={tiles} lost={lost} onSwipe={handleMove}></Board>
      <ActionPanel onNewGame={startGame}></ActionPanel>
    </div>
  );
}

export default App;

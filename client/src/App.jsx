import { useState, useEffect } from 'react';
import Board from "./components/Board";
import ScoreCard from "./components/ScoreCard";
import ActionPanel from './components/ActionPanel'; 
import initializeGameState, { GRID_COUNT } from "./game";
import "./App.css";

function App() {
  const [currentScore, setCurrentScore] = useState(0);              
  const [bestScore, setBestScore] = useState(0);
  const [boardState, setBoardState] = useState(Array(GRID_COUNT));   // init as empty array

  // initialize game state
  useEffect(() => {
    initializeGameState(setCurrentScore, setBoardState);
    console.log("board state:", boardState);
  }, []);

  
  // TODO: add a hook for keyboard movement

  return (
    <>
      <ScoreCard score={currentScore} bestScore={bestScore}></ScoreCard>
      <Board></Board>
      <ActionPanel></ActionPanel>
    </>
  )
}

export default App

import { useEffect, useRef, useState } from "react";
import "./ScoreCard.css";

export const HELP_TEXT = "Arrow keys or swipe. AI previews a move (Expectimax needs no setup; LLM uses Ollama); Auto Play loops.";

function ScoreCard({ score, bestScore }) {
    const [helpOpen, setHelpOpen] = useState(false);
    const helpRef = useRef(null);

    useEffect(() => {
        if (!helpOpen) return;

        function onPointerDown(event) {
            if (!helpRef.current?.contains(event.target)) setHelpOpen(false);
        }

        function onKeyDown(event) {
            if (event.key === "Escape") setHelpOpen(false);
        }

        document.addEventListener("pointerdown", onPointerDown);
        document.addEventListener("keydown", onKeyDown);
        return () => {
            document.removeEventListener("pointerdown", onPointerDown);
            document.removeEventListener("keydown", onKeyDown);
        };
    }, [helpOpen]);

    return (
        <div className="scorecard-background">
            <h1 className="game-title">2048</h1>
            <div className="help" ref={helpRef}>
                <button
                    type="button"
                    className="help-button"
                    aria-label="How to play"
                    aria-expanded={helpOpen}
                    aria-controls="how-to-play"
                    onClick={() => setHelpOpen((open) => !open)}
                >
                    ?
                </button>
                {helpOpen && (
                    <p className="help-text" id="how-to-play">{HELP_TEXT}</p>
                )}
            </div>
            <div className="scorecard">
                <div className="scorecard-title">SCORE</div>
                <div className="scorecard-value">{score}</div>
            </div>
            <div className="scorecard">
                <div className="scorecard-title">BEST</div>
                <div className="scorecard-value">{bestScore}</div>
            </div>
        </div>
    );
}

export default ScoreCard;

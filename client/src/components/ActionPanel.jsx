import "./ActionPanel.css";

function ActionPanel({ onNewGame, onSuggest, canSuggest, suggesting }) {
    return (
        <div className="action-background">
            <button type="button" className="action-button" onClick={onNewGame}>
                New Game
            </button>
            <button
                type="button"
                className="action-button"
                onClick={onSuggest}
                disabled={!canSuggest}
                aria-busy={suggesting || undefined}
            >
                {suggesting ? "Thinking…" : "AI"}
            </button>
        </div>
    );
}

export default ActionPanel;

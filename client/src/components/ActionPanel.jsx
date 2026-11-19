import "./ActionPanel.css";

const MODES = [
    { value: "llm", label: "LLM" },
    { value: "expectimax", label: "Expectimax" },
];

function ActionPanel({ onNewGame, onSuggest, canSuggest, suggesting, mode, onModeChange }) {
    return (
        <div className="action-panel">
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
            <fieldset className="ai-mode" disabled={suggesting}>
                <legend className="ai-mode-legend">AI mode</legend>
                <div className="ai-mode-options" role="radiogroup" aria-label="AI mode">
                    {MODES.map((option) => (
                        <label key={option.value} className="ai-mode-option">
                            <input
                                type="radio"
                                name="ai-mode"
                                value={option.value}
                                checked={mode === option.value}
                                onChange={() => onModeChange(option.value)}
                            />
                            {option.label}
                        </label>
                    ))}
                </div>
            </fieldset>
        </div>
    );
}

export default ActionPanel;

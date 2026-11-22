import { capitalize } from "../suggestHints";
import "./ActionPanel.css";

const MODES = [
    { value: "llm", label: "LLM" },
    { value: "expectimax", label: "Expectimax" },
];

function ActionPanel({
    onNewGame,
    onSuggest,
    canSuggest,
    suggesting,
    autoPlaying,
    onAutoPlayToggle,
    canToggleAutoPlay,
    mode,
    onModeChange,
    pendingMove,
    onApplySuggestion,
    canApplySuggestion,
    hint,
}) {
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
            <button
                type="button"
                className={
                    autoPlaying
                        ? "action-button action-button-auto action-button-auto-active"
                        : "action-button action-button-auto"
                }
                onClick={onAutoPlayToggle}
                disabled={!canToggleAutoPlay}
                aria-pressed={autoPlaying}
            >
                {autoPlaying ? "Stop" : "Auto Play"}
            </button>
            <fieldset className="ai-mode" disabled={autoPlaying}>
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
            {hint && <p className="ai-hint" role="status">{hint}</p>}
            {pendingMove && !autoPlaying && (
                <div className="ai-suggestion">
                    <button
                        type="button"
                        className="action-button action-button-apply"
                        onClick={onApplySuggestion}
                        disabled={!canApplySuggestion}
                    >
                        Play {capitalize(pendingMove)}
                    </button>
                </div>
            )}
        </div>
    );
}

export default ActionPanel;

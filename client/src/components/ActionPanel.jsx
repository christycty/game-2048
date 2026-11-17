import "./ActionPanel.css"

function ActionPanel({ onNewGame }) {
    return (
        <>
            <div className="action-background">
                <button type="button" className="action-button" onClick={onNewGame}>
                    New Game
                </button>
                <button type="button" className="action-button">
                    AI
                </button>
            </div>
        </>
    )
}

export default ActionPanel;
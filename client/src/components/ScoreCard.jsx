import "./ScoreCard.css"

function ScoreCard({score, bestScore}) {
    return (
        <>
            <div className="scorecard-background">
                <div className="scorecard">
                    <div className="scorecard-title">SCORE</div>
                    <div className="scorecard-value">{score}</div>
                </div>
                <div className="scorecard">
                    <div className="scorecard-title">BEST</div>
                    <div className="scorecard-value">{bestScore}</div>
                </div>
            </div>
        </>
    )
}

export default ScoreCard;
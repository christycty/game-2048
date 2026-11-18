import { useLayoutEffect, useRef } from "react";
import { GRID_COUNT, GRID_SIZE, SLIDE_MS } from "../game";
import { swipeDirection } from "../swipe";
import "./Board.css";

// One step is the board's own cell plus gap, so a resize cannot leave the slide behind.
const STEP = "(var(--cell) + var(--gap))";

function tileTransform(row, col) {
    return `translate(calc(${col} * ${STEP}), calc(${row} * ${STEP}))`;
}

function tileZIndex(tile) {
    if (tile.absorbing) return 3;
    if (tile.sliding) return 2;
    return 1;
}

function Tile({ tile }) {
    const ref = useRef(null);
    const fromRow = tile.fromRow ?? tile.row;
    const fromCol = tile.fromCol ?? tile.col;

    useLayoutEffect(() => {
        const element = ref.current;
        if (!element) return;

        const destination = tileTransform(tile.row, tile.col);
        if (fromRow === tile.row && fromCol === tile.col) {
            element.style.transform = destination;
            return;
        }

        // Park on the previous cell for one frame. React does not write `transform`,
        // so a later render cannot cancel this transition.
        element.style.transition = "none";
        element.style.transform = tileTransform(fromRow, fromCol);
        const frame = requestAnimationFrame(() => {
            element.style.transition = `transform ${SLIDE_MS}ms ease-in-out`;
            element.style.transform = destination;
        });
        return () => cancelAnimationFrame(frame);
    }, [tile.row, tile.col, fromRow, fromCol]);

    const classes = ["tile"];
    if (tile.isNew) classes.push("tile-new");
    if (tile.isMerged) classes.push("tile-merged");

    const valueClass = tile.value <= 2048 ? `tile-value-${tile.value}` : "tile-value-super";

    return (
        <div
            ref={ref}
            className={classes.join(" ")}
            style={{ zIndex: tileZIndex(tile) }}
        >
            <div className={`tile-inner ${valueClass}`}>{tile.value}</div>
        </div>
    );
}

function Board({ tiles, lost, onSwipe }) {
    const swipeRef = useRef(null);

    function onPointerDown(event) {
        if (event.pointerType === "mouse" && event.button !== 0) return;
        swipeRef.current = {
            x: event.clientX,
            y: event.clientY,
            pointerId: event.pointerId,
        };
        try {
            event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
            // A synthetic pointer has no capture target.
        }
    }

    function finishSwipe(event) {
        const start = swipeRef.current;
        if (!start || start.pointerId !== event.pointerId) return;
        swipeRef.current = null;

        const direction = swipeDirection(event.clientX - start.x, event.clientY - start.y);
        if (direction) onSwipe(direction);
    }

    return (
        <div className="board-background">
            <div className="board-sizer">
                <div
                    className="board"
                    style={{ "--slide": `${SLIDE_MS}ms`, "--size": GRID_SIZE }}
                    onPointerDown={onPointerDown}
                    onPointerUp={finishSwipe}
                    onPointerCancel={() => {
                        swipeRef.current = null;
                    }}
                >
                    <div className="board-cells">
                        {Array.from({ length: GRID_COUNT }, (_, index) => (
                            <div className="cell" key={index} />
                        ))}
                    </div>
                    <div className="tile-layer">
                        {/* Stable id order so a merge does not reorder DOM nodes mid-slide. */}
                        {[...tiles]
                            .sort((a, b) => a.id - b.id)
                            .map((tile) => (
                                <Tile tile={tile} key={tile.id} />
                            ))}
                    </div>
                    {lost && <div className="game-over">Game over</div>}
                </div>
            </div>
        </div>
    );
}

export default Board;

import { useLayoutEffect, useRef } from "react";
import { SLIDE_MS } from "../game";
import "./Board.css";

const CELL = 90;
const GAP = 12;
const SWIPE_THRESHOLD = 24;

function tileTransform(row, col) {
    const step = CELL + GAP;
    return `translate(${col * step}px, ${row * step}px)`;
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
            style={{ zIndex: tile.id }}
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
        swipeRef.current = null;
        if (!start || start.pointerId !== event.pointerId) return;

        const dx = event.clientX - start.x;
        const dy = event.clientY - start.y;
        if (Math.max(Math.abs(dx), Math.abs(dy)) < SWIPE_THRESHOLD) return;

        const direction = Math.abs(dx) > Math.abs(dy)
            ? (dx > 0 ? "right" : "left")
            : (dy > 0 ? "down" : "up");
        onSwipe(direction);
    }

    return (
        <div className="board-background">
            <div
                className="board"
                style={{
                    "--cell": `${CELL}px`,
                    "--gap": `${GAP}px`,
                    "--slide": `${SLIDE_MS}ms`,
                }}
                onPointerDown={onPointerDown}
                onPointerUp={finishSwipe}
                onPointerCancel={() => {
                    swipeRef.current = null;
                }}
            >
                <div className="board-cells">
                    {Array.from({ length: 16 }, (_, index) => (
                        <div className="cell" key={index} />
                    ))}
                </div>
                <div className="tile-layer">
                    {[...tiles]
                        .sort((a, b) => a.id - b.id)
                        .map((tile) => (
                            <Tile tile={tile} key={tile.id} />
                        ))}
                </div>
                {lost && <div className="game-over">Game over</div>}
            </div>
        </div>
    );
}

export default Board;

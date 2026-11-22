import { useLayoutEffect, useRef } from "react";
import { GRID_COUNT, GRID_SIZE, SLIDE_MS } from "../game";
import { swipeDirection } from "../swipe";
import "./Board.css";

// One step is the board's own cell plus gap, so a resize cannot leave the slide behind.
const STEP = "(var(--cell) + var(--gap))";

function tileTransform(row, col) {
    return `translate(calc(${col} * ${STEP}), calc(${row} * ${STEP}))`;
}

// The tile that disappears into a merge paints above one that only changes cell.
function tileZIndex(tile) {
    if (tile.absorbing) return 3;
    if (tile.sliding) return 2;
    return 1;
}

function Tile({ tile }) {
    const ref = useRef(null);
    // Opening tiles have no origin, so they sit on the cell where they spawned.
    const fromRow = tile.fromRow ?? tile.row;
    const fromCol = tile.fromCol ?? tile.col;

    useLayoutEffect(() => {
        const element = ref.current;
        if (!element) return;

        const destination = tileTransform(tile.row, tile.col);
        // A tile that did not change cell stays put, with no transition to replay.
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

    // tile-new fades the spawn in. tile-merged pops the number that just doubled.
    const classes = ["tile"];
    if (tile.isNew) classes.push("tile-new");
    if (tile.isMerged) classes.push("tile-merged");

    // 4096 and above share one style.
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

function Board({ tiles, lost, won = false, onSwipe }) {
    const swipeRef = useRef(null);

    function onPointerDown(event) {
        // A right-click is not a swipe.
        if (event.pointerType === "mouse" && event.button !== 0) return;
        swipeRef.current = {
            x: event.clientX,
            y: event.clientY,
            pointerId: event.pointerId,
        };
        // Capture so a finger can lift outside the board and the drag still counts.
        try {
            event.currentTarget.setPointerCapture(event.pointerId);
        } catch {
            // A synthetic pointer has no capture target.
        }
    }

    function finishSwipe(event) {
        const start = swipeRef.current;
        // Another pointer ending must not cancel the gesture that is still down.
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
                        // The browser took the pointer, so this drag is not a swipe.
                        swipeRef.current = null;
                    }}
                >
                    {/* Empty cells stay put. Tiles live in their own layer so they can slide across them. */}
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
                    {/* A sibling of the tile layer, so a tile z-index cannot cover this overlay. */}
                    {won && <div className="game-over">You win!</div>}
                    {lost && !won && <div className="game-over">Game over</div>}
                </div>
            </div>
        </div>
    );
}

export default Board;

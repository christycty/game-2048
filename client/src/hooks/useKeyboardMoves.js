import { useEffect, useRef } from "react";

const KEY_DIRECTIONS = {
    ArrowLeft: "left",
    ArrowRight: "right",
    ArrowUp: "up",
    ArrowDown: "down",
};

/**
 * Arrow keys → onMove(direction).
 *
 * onMove is mirrored into a ref after render so the listener stays bound once;
 * callers must keep move policy on refs (not stale closure state).
 */
export function useKeyboardMoves({ onMove }) {
    const onMoveRef = useRef(onMove);

    useEffect(() => {
        onMoveRef.current = onMove;
    });

    useEffect(() => {
        function onKeyDown(event) {
            const direction = KEY_DIRECTIONS[event.key];
            if (!direction) return;
            event.preventDefault();
            onMoveRef.current(direction);
        }

        window.addEventListener("keydown", onKeyDown);
        return () => {
            window.removeEventListener("keydown", onKeyDown);
        };
    }, []);
}

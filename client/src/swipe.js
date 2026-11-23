const SWIPE_THRESHOLD = 24;

// A short drag is ignored. The longer axis picks the direction.
export function swipeDirection(dx, dy, threshold = SWIPE_THRESHOLD) {
    if (Math.max(Math.abs(dx), Math.abs(dy)) < threshold) return null;
    if (Math.abs(dx) > Math.abs(dy)) return dx > 0 ? "right" : "left";
    return dy > 0 ? "down" : "up";
}

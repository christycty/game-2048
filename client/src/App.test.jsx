import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { applyMove, createInitialTiles, SETTLE_MS } from "./game";

vi.mock("./game", async () => {
    const actual = await vi.importActual("./game");
    return {
        ...actual,
        createInitialTiles: vi.fn(),
        applyMove: vi.fn(),
    };
});

const opening = [{ id: 1, row: 0, col: 0, value: 2 }];
const restarted = [{ id: 9, row: 2, col: 2, value: 8 }];

function scoreValue(label) {
    return screen.getByText(label).parentElement.querySelector(".scorecard-value").textContent;
}

function press(key) {
    fireEvent.keyDown(window, { key });
}

beforeEach(() => {
    createInitialTiles.mockReset();
    applyMove.mockReset();
    createInitialTiles.mockReturnValue(opening);
    vi.useFakeTimers();
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
});

test("a move scores after the slide and ignores input until then", () => {
    const resolved = [{ id: 1, row: 0, col: 1, value: 16, isMerged: true }];
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 8,
        visualTiles: [{ id: 1, row: 0, col: 1, value: 8, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: resolved,
        lost: false,
    });

    render(<App />);
    press("ArrowRight");
    press("ArrowDown");

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(scoreValue("SCORE")).toBe("0");
    expect(document.querySelector(".tile-inner").textContent).toBe("8");
    expect(document.querySelector(".tile").className).not.toContain("tile-merged");

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    expect(scoreValue("SCORE")).toBe("8");
    expect(scoreValue("BEST")).toBe("8");
    expect(document.querySelector(".tile-inner").textContent).toBe("16");
    expect(document.querySelector(".tile").className).toContain("tile-merged");

    press("ArrowLeft");
    expect(applyMove).toHaveBeenCalledTimes(2);
    expect(applyMove).toHaveBeenLastCalledWith(resolved, "left");
});

test("a swipe uses the same move path as the arrow keys", () => {
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 4,
        visualTiles: [{ id: 1, row: 0, col: 1, value: 8, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 1, value: 4 }],
        lost: false,
    });

    render(<App />);
    const board = document.querySelector(".board");
    fireEvent.pointerDown(board, { clientX: 10, clientY: 40, pointerId: 1, button: 0, pointerType: "touch" });
    fireEvent.pointerUp(board, { clientX: 100, clientY: 40, pointerId: 1, pointerType: "touch" });

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(document.querySelector(".tile-inner").textContent).toBe("8");
});

test("best score keeps the higher result after a new game", () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    applyMove
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 8,
            visualTiles: [{ id: 1, row: 0, col: 0, value: 2, sliding: true }],
            resolvedTiles: [{ id: 1, row: 0, col: 0, value: 8 }],
            lost: false,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 2,
            visualTiles: [{ id: 9, row: 2, col: 2, value: 8, sliding: true }],
            resolvedTiles: [{ id: 9, row: 2, col: 2, value: 8 }],
            lost: false,
        });

    render(<App />);
    press("ArrowRight");
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    expect(scoreValue("SCORE")).toBe("8");
    expect(scoreValue("BEST")).toBe("8");

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expect(scoreValue("SCORE")).toBe("0");
    expect(scoreValue("BEST")).toBe("8");
    expect(document.querySelector(".tile-inner").textContent).toBe("8");

    press("ArrowLeft");
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    expect(scoreValue("SCORE")).toBe("2");
    expect(scoreValue("BEST")).toBe("8");
});

test("a new game drops a slide that has not finished", () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 8,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    press("ArrowRight");
    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    expect(scoreValue("SCORE")).toBe("0");
    expect(scoreValue("BEST")).toBe("0");
    expect(screen.getByText("8")).toBeTruthy();
    expect(screen.queryByText("2")).toBeNull();

    press("ArrowLeft");
    expect(applyMove).toHaveBeenLastCalledWith(restarted, "left");
});

test("a lost game ignores later moves", () => {
    const resolved = [{ id: 1, row: 0, col: 0, value: 2 }];
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 4,
        visualTiles: resolved,
        resolvedTiles: resolved,
        lost: true,
    });

    render(<App />);
    press("ArrowUp");
    expect(screen.queryByText("Game over")).toBeNull();

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    expect(screen.getByText("Game over")).toBeTruthy();
    expect(scoreValue("SCORE")).toBe("4");
    press("ArrowLeft");
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a move that does not change the board can be followed immediately", () => {
    applyMove.mockReturnValue({
        moved: false,
        scoreGained: 0,
        visualTiles: opening,
        resolvedTiles: opening,
        lost: false,
    });

    render(<App />);
    press("ArrowLeft");
    press("ArrowLeft");
    press("Enter");

    expect(applyMove).toHaveBeenCalledTimes(2);
    expect(scoreValue("SCORE")).toBe("0");
});

test("a new game clears a loss and accepts another move", () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    const resolved = [{ id: 1, row: 0, col: 0, value: 2 }];
    applyMove
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 4,
            visualTiles: resolved,
            resolvedTiles: resolved,
            lost: true,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 2,
            visualTiles: [{ id: 9, row: 2, col: 2, value: 8, sliding: true }],
            resolvedTiles: restarted,
            lost: false,
        });

    render(<App />);
    press("ArrowUp");
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    expect(screen.getByText("Game over")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expect(screen.queryByText("Game over")).toBeNull();

    press("ArrowLeft");
    expect(applyMove).toHaveBeenLastCalledWith(restarted, "left");
});

test("the AI control stays inactive until it can suggest a move", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);
});

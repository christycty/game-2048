import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { suggestMove, SuggestError } from "./api";
import { applyMove, AUTO_PLAY_GAP_MS, createInitialTiles, SETTLE_MS } from "./game";

// These tests lock input and score timing. The move rules are covered in game.test.js.
vi.mock("./game", async () => {
    const actual = await vi.importActual("./game");
    return {
        ...actual,
        createInitialTiles: vi.fn(),
        applyMove: vi.fn(),
    };
});

vi.mock("./api", async () => {
    const actual = await vi.importActual("./api");
    return {
        ...actual,
        suggestMove: vi.fn(),
    };
});

// The board before any move, and the board a new game deals.
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
    suggestMove.mockReset();
    createInitialTiles.mockReturnValue(opening);
    // The clock stays still until a test moves it past the end of the slide.
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
    // This key arrives while the slide is still playing, so it is ignored.
    press("ArrowDown");

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(scoreValue("SCORE")).toBe("0");
    expect(document.querySelector(".tile-inner").textContent).toBe("8");
    expect(document.querySelector(".tile").className).not.toContain("tile-merged");

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    // The slide has finished, so the score updates and the next key is accepted.
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
    // The finger travels farther sideways than up or down, so the move is to the right.
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

    // New Game clears the score and keeps the best score from the first game.
    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expect(scoreValue("SCORE")).toBe("0");
    expect(scoreValue("BEST")).toBe("8");
    expect(document.querySelector(".tile-inner").textContent).toBe("8");

    press("ArrowLeft");
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    // The second game scores 2, which does not replace the best of 8.
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
    // New Game happens before the slide finishes. The old 2 must not come back, and its score must not be added.
    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    expect(scoreValue("SCORE")).toBe("0");
    expect(scoreValue("BEST")).toBe("0");
    // The 8 is the tile dealt by the new game.
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
    // The overlay waits until the slide finishes.
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
    // Enter is not a direction. Both Left presses count, because a blocked move does not lock the board.
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
    // The overlay is gone, and the next key moves the new board.
    expect(screen.queryByText("Game over")).toBeNull();

    press("ArrowLeft");
    expect(applyMove).toHaveBeenLastCalledWith(restarted, "left");
});

test("the AI control is active when the board can still move", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("the AI control stays inactive after the game is lost", () => {
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
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);
});

test("an AI suggestion shows the move without applying it", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "Opens space on the left.",
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    expect(screen.getByRole("button", { name: "Thinking…" }).disabled).toBe(true);

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(suggestMove).toHaveBeenCalledWith(
        [
            [2, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        "llm",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Right. Opens space on the left.",
    );
    expect(screen.getByRole("button", { name: "Play Right" }).disabled).toBe(false);
});

test("applying an AI suggestion plays the pending move", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "Opens space on the left.",
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("button", { name: "Play Right" }));

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(screen.queryByRole("button", { name: "Play Right" })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
});

test("expectimax mode is sent to the suggestion API", async () => {
    suggestMove.mockResolvedValue({
        move: "up",
        mode: "expectimax",
        source: "expectimax",
        reason: "Score of each direction: Left = N/A, Right = 1053.4, Up = 1200.0, Down = 771.2",
    });

    render(<App />);
    fireEvent.click(screen.getByRole("radio", { name: "Expectimax" }));
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledWith(
        [
            [2, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        "expectimax",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Up. Score of each direction: Left = N/A, Right = 1053.4, Up = 1200.0, Down = 771.2",
    );
    expect(screen.getByRole("button", { name: "Play Up" })).toBeTruthy();
});

test("a fallback response reports the miss and offers no move", async () => {
    suggestMove.mockResolvedValue({
        move: "left",
        mode: "llm",
        source: "fallback",
        reason: null,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    // The fixed order is not a suggestion, so the player is asked to try again.
    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("AI could not suggest a move");
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a rate-limited suggestion tells the player to wait", async () => {
    suggestMove.mockRejectedValue(new SuggestError("suggestion rate limit", { status: 429 }));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe(
        "Too many suggestions. Wait a moment and try again.",
    );
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a failed AI suggestion leaves the board alone and reports the miss", async () => {
    suggestMove.mockRejectedValue(new Error("offline"));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("AI could not suggest a move");
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a player move during an AI request drops the late suggestion", async () => {
    let finishSuggest;
    let seenSignal;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((resolve) => {
                seenSignal = options.signal;
                finishSuggest = resolve;
            }),
    );
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 1, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 1, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);

    press("ArrowRight");

    expect(seenSignal.aborted).toBe(true);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");

    await act(async () => {
        finishSuggest({
            move: "left",
            mode: "llm",
            source: "llm",
            reason: "Would have gone left.",
        });
        await Promise.resolve();
    });

    // The late suggestion must not add a second move or leave its reason on screen.
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
});

test("a blocked move during an AI request keeps the suggestion", async () => {
    let finishSuggest;
    suggestMove.mockImplementation(
        () =>
            new Promise((resolve) => {
                finishSuggest = resolve;
            }),
    );
    applyMove.mockReturnValue({
        moved: false,
        scoreGained: 0,
        visualTiles: opening,
        resolvedTiles: opening,
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    press("ArrowLeft");

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Thinking…" }).disabled).toBe(true);

    await act(async () => {
        finishSuggest({
            move: "right",
            mode: "expectimax",
            source: "expectimax",
            reason: "Score of each direction: Left = N/A, Right = 900.0, Up = N/A, Down = 800.0",
        });
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Right. Score of each direction: Left = N/A, Right = 900.0, Up = N/A, Down = 800.0",
    );
    expect(screen.getByRole("button", { name: "Play Right" })).toBeTruthy();
});

test("changing AI mode clears the pending suggestion", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "Opens space on the left.",
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "Play Right" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Expectimax" }));

    expect(screen.getByRole("radio", { name: "Expectimax" }).checked).toBe(true);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("button", { name: "Play Right" })).toBeNull();
});

test("changing AI mode during Thinking aborts the in-flight suggest", async () => {
    let seenSignal;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);

    fireEvent.click(screen.getByRole("radio", { name: "Expectimax" }));

    expect(seenSignal.aborted).toBe(true);
    expect(screen.getByRole("radio", { name: "Expectimax" }).checked).toBe(true);
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("auto play applies a suggestion without waiting for Play", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: "Opens space on the left.",
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("radio", { name: "Expectimax" }));
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(suggestMove).toHaveBeenCalledWith(
        [
            [2, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        "expectimax",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("radio", { name: "Expectimax" }).checked).toBe(true);
    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Right. Opens space on the left.",
    );
});

test("auto play keeps the selected LLM mode for the first request", async () => {
    let finishSuggest;
    suggestMove.mockImplementation(
        () =>
            new Promise((resolve) => {
                finishSuggest = resolve;
            }),
    );
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    expect(screen.getByRole("radio", { name: "LLM" }).checked).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    expect(screen.getByRole("radio", { name: "LLM" }).checked).toBe(true);
    expect(screen.queryByRole("status")).toBeNull();

    await act(async () => {
        finishSuggest({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: null,
        });
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledWith(
        [
            [2, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        "llm",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right.");
    expect(screen.getByRole("radio", { name: "LLM" }).checked).toBe(true);
});

test("auto play requests another suggestion after the slide settles", async () => {
    const afterFirst = [{ id: 1, row: 0, col: 3, value: 2 }];
    let finishSecondSuggest;
    suggestMove
        .mockResolvedValueOnce({
            move: "right",
            mode: "expectimax",
            source: "expectimax",
            reason: null,
        })
        .mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finishSecondSuggest = resolve;
                }),
        );
    applyMove
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
            resolvedTiles: afterFirst,
            lost: false,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 3, col: 3, value: 2, fromRow: 0, fromCol: 3, sliding: true }],
            resolvedTiles: [{ id: 1, row: 3, col: 3, value: 2 }],
            lost: false,
        });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right.");

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS);
        await Promise.resolve();
    });

    // The gap after settle must pass before the next suggestion.
    expect(suggestMove).toHaveBeenCalledTimes(1);

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    // Hint from the previous step stays visible while the next request is in flight.
    expect(suggestMove).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right.");

    await act(async () => {
        finishSecondSuggest({
            move: "down",
            mode: "expectimax",
            source: "expectimax",
            reason: null,
        });
        await Promise.resolve();
    });

    expect(applyMove).toHaveBeenCalledTimes(2);
    expect(applyMove).toHaveBeenLastCalledWith(afterFirst, "down");
    expect(screen.getByRole("status").textContent).toBe("Suggested: Down.");
});

test("stopping auto play ends the loop after the current move", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: null,
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("stopping auto play during the gap re-enables AI without waiting out the pause", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: null,
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS);
        await Promise.resolve();
    });

    // Still inside the post-settle gap; busy is held for the pause.
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
    expect(screen.getByRole("button", { name: "Auto Play" }).disabled).toBe(false);

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a fallback during auto play stops the loop", async () => {
    suggestMove.mockResolvedValue({
        move: "left",
        mode: "expectimax",
        source: "fallback",
        reason: null,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe("AI could not suggest a move");
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
});

test("stopping auto play during Thinking aborts the suggest request", async () => {
    let rejectSuggest;
    let seenSignal;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                rejectSuggest = reject;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(seenSignal.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
    // Abort is silent: no failure hint / Play.
    expect(screen.queryByRole("status")).toBeNull();
    expect(applyMove).not.toHaveBeenCalled();

    await act(async () => {
        // The abort listener may already have rejected; settle any leftover promise.
        rejectSuggest?.(new DOMException("Aborted", "AbortError"));
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
});

test("a manual move during auto play stops the loop", async () => {
    let finishSuggest;
    suggestMove.mockImplementation(
        () =>
            new Promise((resolve) => {
                finishSuggest = resolve;
            }),
    );
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 1, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 1, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));
    press("ArrowRight");

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );

    await act(async () => {
        finishSuggest({
            move: "left",
            mode: "expectimax",
            source: "expectimax",
            reason: null,
        });
        await Promise.resolve();
    });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    // The cancelled suggestion must not restart auto-play or apply a second move.
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(suggestMove).toHaveBeenCalledTimes(1);
});

test("auto play applies a pending suggestion then continues", async () => {
    const afterPending = [{ id: 1, row: 0, col: 3, value: 2 }];
    suggestMove
        .mockResolvedValueOnce({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "Opens space on the left.",
        })
        .mockResolvedValueOnce({
            move: "down",
            mode: "expectimax",
            source: "expectimax",
            reason: null,
        });
    applyMove
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
            resolvedTiles: afterPending,
            lost: false,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 3, col: 3, value: 2, fromRow: 0, fromCol: 3, sliding: true }],
            resolvedTiles: [{ id: 1, row: 3, col: 3, value: 2 }],
            lost: false,
        });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "Play Right" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(screen.getByRole("radio", { name: "LLM" }).checked).toBe(true);
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(2);
    expect(suggestMove).toHaveBeenLastCalledWith(
        [
            [0, 0, 0, 2],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        "llm",
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(applyMove).toHaveBeenLastCalledWith(afterPending, "down");
});

test("a blocked pending move when starting auto play stops the loop", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "Opens space on the left.",
    });
    applyMove.mockReturnValue({
        moved: false,
        scoreGained: 0,
        visualTiles: opening,
        resolvedTiles: opening,
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "Play Right" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(screen.getByRole("status").textContent).toBe("AI could not suggest a move");
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a blocked auto-applied suggestion stops the loop", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: null,
    });
    applyMove.mockReturnValue({
        moved: false,
        scoreGained: 0,
        visualTiles: opening,
        resolvedTiles: opening,
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expect(screen.getByRole("status").textContent).toBe("AI could not suggest a move");
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a loss during auto play stops the loop", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: null,
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 4,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: true,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(screen.getByText("Game over")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a rate limit during auto play stops the loop", async () => {
    suggestMove.mockRejectedValue(new SuggestError("suggestion rate limit", { status: 429 }));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe(
        "Too many suggestions. Wait a moment and try again.",
    );
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a new game during auto play cancels the next suggestion", async () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: null,
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expect(screen.getByRole("button", { name: "Auto Play" }).getAttribute("aria-pressed")).toBe(
        "false",
    );

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
});

test("a new game during Thinking aborts the in-flight suggest", async () => {
    let seenSignal;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));

    expect(seenSignal.aborted).toBe(true);
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();

    await act(async () => {
        await Promise.resolve();
    });
});

test("unmount aborts an in-flight suggest", async () => {
    let seenSignal;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);

    unmount();

    expect(seenSignal.aborted).toBe(true);
});

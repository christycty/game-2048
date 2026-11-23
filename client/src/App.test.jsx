import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import App from "./App.jsx";
import { suggestMove, SuggestError, LIMIT_CAPACITY, LIMIT_SPEND } from "./suggest/api";
import {
    applyMove,
    AUTO_PLAY_CAPACITY_MAX_RETRIES,
    AUTO_PLAY_FALLBACK_MAX_RETRIES,
    AUTO_PLAY_FALLBACK_RETRY_MS,
    AUTO_PLAY_GAP_MS,
    createInitialTiles,
    SETTLE_MS,
} from "./game/game";
import {
    HINT_CAPACITY_BUSY,
    HINT_CAPACITY_RETRYING,
    HINT_SPEND_CAP,
    HINT_SUGGEST_FAILED,
    HINT_SUGGEST_RETRYING,
} from "./suggest/suggestHints";

// These tests lock input and score timing. The move rules are covered in game.test.js.
vi.mock("./game/game", async () => {
    const actual = await vi.importActual("./game/game");
    return {
        ...actual,
        createInitialTiles: vi.fn(),
        applyMove: vi.fn(),
    };
});

vi.mock("./suggest/api", async () => {
    const actual = await vi.importActual("./suggest/api");
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

function expectStoppedControls({
    aiDisabled = false,
    autoDisabled = false,
    status,
}) {
    if (status === undefined) {
        throw new Error("expectStoppedControls requires an explicit status (string or null)");
    }
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(aiDisabled);
    const autoBtn = screen.getByRole("button", { name: "Auto Play" });
    expect(autoBtn.getAttribute("aria-pressed")).toBe("false");
    expect(autoBtn.disabled).toBe(autoDisabled);
    expect(screen.getByRole("group", { name: "AI mode" }).disabled).toBe(false);
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    if (status === null) {
        expect(screen.queryByRole("status")).toBeNull();
    } else {
        expect(screen.getByRole("status").textContent).toBe(status);
    }
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
        won: false,
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

test("a won game shows You win and ignores later moves", () => {
    const resolved = [{ id: 1, row: 0, col: 0, value: 2048 }];
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 2048,
        visualTiles: resolved,
        resolvedTiles: resolved,
        lost: false,
        won: true,
    });

    render(<App />);
    press("ArrowLeft");
    expect(screen.queryByText("You win!")).toBeNull();

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });

    expect(screen.getByText("You win!")).toBeTruthy();
    expect(screen.queryByText("Game over")).toBeNull();
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);
    press("ArrowDown");
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a new game clears a win and accepts another move", () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    const resolved = [{ id: 1, row: 0, col: 0, value: 2048 }];
    applyMove
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 2048,
            visualTiles: resolved,
            resolvedTiles: resolved,
            lost: false,
            won: true,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 2,
            visualTiles: [{ id: 9, row: 2, col: 2, value: 8, sliding: true }],
            resolvedTiles: restarted,
            lost: false,
            won: false,
        });

    render(<App />);
    press("ArrowUp");
    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    expect(screen.getByText("You win!")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expect(screen.queryByText("You win!")).toBeNull();

    press("ArrowLeft");
    expect(applyMove).toHaveBeenLastCalledWith(restarted, "left");
});

test("a new game shows the opening deal size from createInitialTiles", () => {
    const dense = [
        { id: 1, row: 0, col: 0, value: 2 },
        { id: 2, row: 0, col: 1, value: 2 },
        { id: 3, row: 0, col: 2, value: 2 },
        { id: 4, row: 0, col: 3, value: 2 },
        { id: 5, row: 1, col: 0, value: 2 },
    ];
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(dense);

    render(<App />);
    expect(document.querySelectorAll(".tile-inner")).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expect(document.querySelectorAll(".tile-inner")).toHaveLength(5);
    expect([...document.querySelectorAll(".tile-inner")].every((node) => node.textContent === "2")).toBe(
        true,
    );
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
        expect.objectContaining({
            signal: expect.any(AbortSignal),
            shouldReportOutcome: expect.any(Function),
        }),
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
        reason: "Expected score vs Up: Left not possible, Right -146.6, Down -428.8",
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
        expect.objectContaining({
            signal: expect.any(AbortSignal),
            shouldReportOutcome: expect.any(Function),
        }),
    );
    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Up. Expected score vs Up: Left not possible, Right -146.6, Down -428.8",
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
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("a spend-capped suggestion tells the player to wait", async () => {
    suggestMove.mockRejectedValue(
        new SuggestError("too many suggestions", {
            status: 429,
            limitReason: LIMIT_SPEND,
            retryAfter: 60,
        }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_SPEND_CAP });

    await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
});

test("a capacity-busy suggestion tells the player the model is busy", async () => {
    suggestMove.mockRejectedValue(
        new SuggestError("model busy", {
            status: 429,
            limitReason: LIMIT_CAPACITY,
            retryAfter: 1,
        }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_CAPACITY_BUSY });

    await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("a failed AI suggestion leaves the board alone and reports the miss", async () => {
    suggestMove.mockRejectedValue(new Error("offline"));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
});

test("a player move during an AI request drops the late suggestion", async () => {
    let finishSuggest;
    let seenSignal;
    let shouldReportOutcome;
    suggestMove.mockImplementation((_board, _mode, options = {}) => {
        seenSignal = options.signal;
        shouldReportOutcome = options.shouldReportOutcome;
        return new Promise((resolve) => {
            finishSuggest = resolve;
        });
    });
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
    expect(typeof shouldReportOutcome).toBe("function");
    expect(shouldReportOutcome()).toBe(true);

    press("ArrowRight");

    expect(seenSignal.aborted).toBe(true);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    // Board-changing move bumps the suggest token; fail/rate_limit must not beacon.
    expect(shouldReportOutcome()).toBe(false);

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
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    expectStoppedControls({ status: null });
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
            reason: "Expected score vs Right: Left not possible, Up not possible, Down -100.0",
        });
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Right. Expected score vs Right: Left not possible, Up not possible, Down -100.0",
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
    expectStoppedControls({ status: null });
});

test("changing AI mode during Thinking aborts the in-flight suggest", async () => {
    let seenSignal;
    let seenShouldReport;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                seenShouldReport = options.shouldReportOutcome;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);
    expect(seenShouldReport()).toBe(true);

    fireEvent.click(screen.getByRole("radio", { name: "Expectimax" }));

    expect(seenSignal.aborted).toBe(true);
    expect(seenShouldReport()).toBe(false);
    expect(screen.getByRole("radio", { name: "Expectimax" }).checked).toBe(true);
    expectStoppedControls({ status: null });

    await act(async () => {
        await Promise.resolve();
    });

    expectStoppedControls({ status: null });
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
        expect.objectContaining({
            signal: expect.any(AbortSignal),
            shouldReportOutcome: expect.any(Function),
        }),
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
        expect.objectContaining({
            signal: expect.any(AbortSignal),
            shouldReportOutcome: expect.any(Function),
        }),
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
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: "Suggested: Right." });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expectStoppedControls({ status: "Suggested: Right." });
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

    expectStoppedControls({ status: "Suggested: Right." });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expectStoppedControls({ status: "Suggested: Right." });
    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a fallback during auto play retries then continues", async () => {
    suggestMove
        .mockResolvedValueOnce({
            move: "left",
            mode: "expectimax",
            source: "fallback",
            reason: null,
        })
        .mockResolvedValue({
            move: "right",
            mode: "expectimax",
            source: "expectimax",
            reason: "ok",
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

    expect(applyMove).not.toHaveBeenCalled();
    expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(suggestMove).toHaveBeenCalledTimes(1);

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(2);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. ok");
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
});

test("a fallback during auto play stops after retries are exhausted", async () => {
    suggestMove.mockResolvedValue({
        move: "left",
        mode: "expectimax",
        source: "fallback",
        reason: null,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    for (let attempt = 0; attempt < AUTO_PLAY_FALLBACK_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
        expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe(
            "true",
        );
        await act(async () => {
            vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
            await Promise.resolve();
        });
    }

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(AUTO_PLAY_FALLBACK_MAX_RETRIES + 1);
    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(AUTO_PLAY_FALLBACK_MAX_RETRIES + 1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("stopping auto play during Thinking aborts the suggest request", async () => {
    let rejectSuggest;
    let seenSignal;
    let seenShouldReport;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                seenShouldReport = options.shouldReportOutcome;
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
    expect(seenShouldReport()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(seenSignal.aborted).toBe(true);
    expect(seenShouldReport()).toBe(false);
    // Abort is silent: no failure hint / Play.
    expectStoppedControls({ status: null });
    expect(applyMove).not.toHaveBeenCalled();

    await act(async () => {
        // The abort listener may already have rejected; settle any leftover promise.
        rejectSuggest?.(new DOMException("Aborted", "AbortError"));
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: null });
});

test("a token-matched AbortError during Auto Play Thinking stops the loop", async () => {
    // Simulates HTTP 499 / disconnect mapped to AbortError without a local abort() (token still current).
    let rejectSuggest;
    suggestMove.mockImplementation(
        () =>
            new Promise((_resolve, reject) => {
                rejectSuggest = reject;
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");

    await act(async () => {
        rejectSuggest(new DOMException("Aborted", "AbortError"));
        await Promise.resolve();
    });

    expectStoppedControls({ status: null });
    expect(applyMove).not.toHaveBeenCalled();
});

test("a manual move during auto play stops the loop", async () => {
    let finishSuggest;
    let seenSignal;
    let seenShouldReport;
    suggestMove.mockImplementation((_board, _mode, options = {}) => {
        seenSignal = options.signal;
        seenShouldReport = options.shouldReportOutcome;
        return new Promise((resolve) => {
            finishSuggest = resolve;
        });
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 1, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 1, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);
    expect(seenShouldReport()).toBe(true);

    press("ArrowRight");

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(seenSignal.aborted).toBe(true);
    expect(seenShouldReport()).toBe(false);
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

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
    expectStoppedControls({ status: null });
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
        expect.objectContaining({
            signal: expect.any(AbortSignal),
            shouldReportOutcome: expect.any(Function),
        }),
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
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });
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
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });
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

    expect(screen.getByRole("status").textContent).toBe("Suggested: Right.");

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(screen.getByText("Game over")).toBeTruthy();
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });
    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a win during auto play stops the loop", async () => {
    suggestMove.mockResolvedValue({
        move: "left",
        mode: "expectimax",
        source: "expectimax",
        reason: null,
    });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 2048,
        visualTiles: [{ id: 1, row: 0, col: 0, value: 1024, fromRow: 0, fromCol: 1, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 0, value: 2048, isMerged: true }],
        lost: false,
        won: true,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe("Suggested: Left.");

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(screen.getByText("You win!")).toBeTruthy();
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });
    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
});

test("a spend rate limit during auto play stops the loop", async () => {
    suggestMove.mockRejectedValue(
        new SuggestError("too many suggestions", {
            status: 429,
            limitReason: LIMIT_SPEND,
            retryAfter: 60,
        }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_SPEND_CAP });

    await act(async () => {
        vi.advanceTimersByTime(60_000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("capacity busy during auto play retries then continues", async () => {
    suggestMove
        .mockRejectedValueOnce(
            new SuggestError("model busy", {
                status: 429,
                limitReason: LIMIT_CAPACITY,
                retryAfter: 1,
            }),
        )
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
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

    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(suggestMove).toHaveBeenCalledTimes(1);

    await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(2);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. ok");
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
});

test("capacity busy during auto play stops after retries are exhausted", async () => {
    suggestMove.mockRejectedValue(
        new SuggestError("model busy", {
            status: 429,
            limitReason: LIMIT_CAPACITY,
            retryAfter: 1,
        }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    for (let attempt = 0; attempt < AUTO_PLAY_CAPACITY_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
        expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe(
            "true",
        );
        await act(async () => {
            vi.advanceTimersByTime(1000);
            await Promise.resolve();
        });
    }

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(AUTO_PLAY_CAPACITY_MAX_RETRIES + 1);
    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_CAPACITY_BUSY });

    await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(AUTO_PLAY_CAPACITY_MAX_RETRIES + 1);
    expect(applyMove).not.toHaveBeenCalled();
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
    expectStoppedControls({ status: null });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expectStoppedControls({ status: null });
});

test("a new game during Thinking aborts the in-flight suggest", async () => {
    let seenSignal;
    let seenShouldReport;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                seenShouldReport = options.shouldReportOutcome;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);
    expect(seenShouldReport()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));

    expect(seenSignal.aborted).toBe(true);
    expect(seenShouldReport()).toBe(false);
    expectStoppedControls({ status: null });

    await act(async () => {
        await Promise.resolve();
    });

    expectStoppedControls({ status: null });
});

test("unmount aborts an in-flight suggest", async () => {
    let seenSignal;
    let seenShouldReport;
    suggestMove.mockImplementation(
        (_board, _mode, options = {}) =>
            new Promise((_resolve, reject) => {
                seenSignal = options.signal;
                seenShouldReport = options.shouldReportOutcome;
                options.signal?.addEventListener("abort", () => {
                    reject(new DOMException("Aborted", "AbortError"));
                });
            }),
    );

    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(seenSignal).toBeInstanceOf(AbortSignal);
    expect(seenSignal.aborted).toBe(false);
    expect(seenShouldReport()).toBe(true);

    unmount();

    expect(seenSignal.aborted).toBe(true);
    expect(seenShouldReport()).toBe(false);
});

test("unmount mid-slide during auto play cancels the pending settle timer", async () => {
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

    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);

    unmount();

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
});

test("unmount during the post-settle auto play gap cancels the pending gap timer", async () => {
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

    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    unmount();

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
});

test("unmount during a capacity retry backoff cancels the retry timer", async () => {
    let seenShouldReport;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenShouldReport = options.shouldReportOutcome;
            return Promise.reject(
                new SuggestError("model busy", {
                    status: 429,
                    limitReason: LIMIT_CAPACITY,
                    retryAfter: 1,
                }),
            );
        })
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });

    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(seenShouldReport()).toBe(true);

    unmount();

    expect(seenShouldReport()).toBe(false);

    await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("unmount during a fallback retry backoff cancels the retry timer", async () => {
    let seenShouldReport;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenShouldReport = options.shouldReportOutcome;
            return Promise.resolve({
                move: "left",
                mode: "llm",
                source: "fallback",
                reason: null,
            });
        })
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });

    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(seenShouldReport()).toBe(true);

    unmount();

    expect(seenShouldReport()).toBe(false);

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("stopping auto play during retry backoff clears retrying copy, re-enables AI, and cancels retry", async () => {
    let seenShouldReport;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenShouldReport = options.shouldReportOutcome;
            return Promise.reject(
                new SuggestError("model busy", {
                    status: 429,
                    limitReason: LIMIT_CAPACITY,
                    retryAfter: 2,
                }),
            );
        })
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);
    expect(seenShouldReport()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(seenShouldReport()).toBe(false);
    expectStoppedControls({ status: null });
    expect(applyMove).not.toHaveBeenCalled();

    await act(async () => {
        vi.advanceTimersByTime(2000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("manual move during retry backoff invalidates the retry token, clears status, and takes control", async () => {
    let seenShouldReport;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenShouldReport = options.shouldReportOutcome;
            return Promise.reject(
                new SuggestError("model busy", {
                    status: 429,
                    limitReason: LIMIT_CAPACITY,
                    retryAfter: 2,
                }),
            );
        })
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 3, col: 0, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 3, col: 0, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(seenShouldReport()).toBe(true);

    press("ArrowDown");
    // Proves abortInFlightSuggest ran before stopAutoPlay cleared retryTimerRef.
    expect(seenShouldReport()).toBe(false);
    expect(applyMove).toHaveBeenCalledWith(expect.anything(), "down");
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + 2000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expectStoppedControls({ status: null });
});

test("applying a pending suggestion that does not move clears Play and reports failure", async () => {
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

    expect(screen.getByRole("button", { name: "Play Right" }).disabled).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Play Right" }));

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(opening, "right");
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });
});

test("a server or transport failure during auto play stops immediately without retrying", async () => {
    suggestMove.mockRejectedValue(new SuggestError("suggest failed: 500", { status: 500 }));

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS + 1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("stopping auto play during retry Attempt 2 Thinking aborts the retry and clears retrying status", async () => {
    let seenAttempt2Signal;
    let seenAttempt2ShouldReport;
    let rejectAttempt2;
    suggestMove
        .mockRejectedValueOnce(
            new SuggestError("model busy", {
                status: 429,
                limitReason: LIMIT_CAPACITY,
                retryAfter: 1,
            }),
        )
        .mockImplementationOnce(
            (_board, _mode, options = {}) =>
                new Promise((_resolve, reject) => {
                    seenAttempt2Signal = options.signal;
                    seenAttempt2ShouldReport = options.shouldReportOutcome;
                    rejectAttempt2 = reject;
                    options.signal?.addEventListener("abort", () => {
                        reject(new DOMException("Aborted", "AbortError"));
                    });
                }),
        );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(suggestMove).toHaveBeenCalledTimes(1);

    await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("button", { name: "Thinking…" }).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(seenAttempt2Signal.aborted).toBe(false);
    expect(seenAttempt2ShouldReport()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(seenAttempt2Signal.aborted).toBe(true);
    expect(seenAttempt2ShouldReport()).toBe(false);
    expectStoppedControls({ status: null });

    await act(async () => {
        rejectAttempt2?.(new DOMException("Aborted", "AbortError"));
        await Promise.resolve();
    });

    expectStoppedControls({ status: null });
    expect(applyMove).not.toHaveBeenCalled();
});

test("capacity retry budget resets after a successful move and after Stop", async () => {
    const busyError = new SuggestError("model busy", {
        status: 429,
        limitReason: LIMIT_CAPACITY,
        retryAfter: 1,
    });
    for (let i = 0; i < AUTO_PLAY_CAPACITY_MAX_RETRIES; i += 1) {
        suggestMove.mockRejectedValueOnce(busyError);
    }
    suggestMove.mockResolvedValueOnce({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "ok",
    });
    suggestMove.mockRejectedValue(busyError);
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    for (let attempt = 0; attempt < AUTO_PLAY_CAPACITY_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
        await act(async () => {
            vi.advanceTimersByTime(1000);
            await Promise.resolve();
        });
    }

    // Move 1 succeeds on the final retry, resetting the capacity counter for Move 2.
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. ok");

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    // Move 2 gets a full AUTO_PLAY_CAPACITY_MAX_RETRIES budget again before exhausting.
    for (let attempt = 0; attempt < AUTO_PLAY_CAPACITY_MAX_RETRIES; attempt += 1) {
        expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
        expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe(
            "true",
        );
        await act(async () => {
            vi.advanceTimersByTime(1000);
            await Promise.resolve();
        });
    }

    expectStoppedControls({ status: HINT_CAPACITY_BUSY });

    // Restarting Auto Play after Stop/exhaustion also starts with a fresh retry budget.
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    for (let attempt = 0; attempt < AUTO_PLAY_CAPACITY_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
        if (attempt === AUTO_PLAY_CAPACITY_MAX_RETRIES - 1) {
            fireEvent.click(screen.getByRole("button", { name: "Stop" }));
            expectStoppedControls({ status: null });
        } else {
            await act(async () => {
                vi.advanceTimersByTime(1000);
                await Promise.resolve();
            });
        }
    }

    // Start once more after explicit Stop: full retry budget is available again.
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));
    for (let attempt = 0; attempt < AUTO_PLAY_CAPACITY_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
        await act(async () => {
            vi.advanceTimersByTime(1000);
            await Promise.resolve();
        });
    }
    await act(async () => {
        await Promise.resolve();
    });
    expectStoppedControls({ status: HINT_CAPACITY_BUSY });
});

test("new game during the post-settle auto play gap clears status and cancels the next suggest", async () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: "ok",
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

    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. ok");
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expectStoppedControls({ status: null });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expectStoppedControls({ status: null });
});

test("manual move during the post-settle auto play gap takes control and cancels the next suggest", async () => {
    const afterAuto = [{ id: 1, row: 0, col: 3, value: 2 }];
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "expectimax",
        source: "expectimax",
        reason: "ok",
    });
    applyMove
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
            resolvedTiles: afterAuto,
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

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS);
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. ok");
    press("ArrowDown");

    expect(applyMove).toHaveBeenLastCalledWith(afterAuto, "down");
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(2);
    expectStoppedControls({ status: null });
});

test("stopping auto play during fallback retry backoff clears status, re-enables controls, and cancels retry", async () => {
    let seenShouldReport;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenShouldReport = options.shouldReportOutcome;
            return Promise.resolve({
                move: "left",
                mode: "llm",
                source: "fallback",
                reason: null,
            });
        })
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
    expect(seenShouldReport()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(seenShouldReport()).toBe(false);
    expectStoppedControls({ status: null });

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).not.toHaveBeenCalled();
});

test("manual move during fallback retry backoff clears status, takes control, and cancels retry", async () => {
    let seenShouldReport;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenShouldReport = options.shouldReportOutcome;
            return Promise.resolve({
                move: "left",
                mode: "llm",
                source: "fallback",
                reason: null,
            });
        })
        .mockResolvedValue({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 3, col: 0, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 3, col: 0, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
    expect(seenShouldReport()).toBe(true);

    press("ArrowDown");

    expect(seenShouldReport()).toBe(false);
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_FALLBACK_RETRY_MS);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledTimes(1);
    expectStoppedControls({ status: null });
});

test("a blocked manual move during auto play Thinking preserves the in-flight request", async () => {
    let finishSuggest;
    let seenSignal;
    let seenShouldReport;
    suggestMove.mockImplementation((_board, _mode, options = {}) => {
        seenSignal = options.signal;
        seenShouldReport = options.shouldReportOutcome;
        return new Promise((resolve) => {
            finishSuggest = resolve;
        });
    });
    applyMove
        .mockReturnValueOnce({
            moved: false,
            scoreGained: 0,
            visualTiles: opening,
            resolvedTiles: opening,
            lost: false,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
            resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
            lost: false,
        });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    press("ArrowLeft");

    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(seenSignal.aborted).toBe(false);
    expect(seenShouldReport()).toBe(true);
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Thinking…" }).disabled).toBe(true);
    expect(screen.getByRole("group", { name: "AI mode" }).disabled).toBe(true);

    await act(async () => {
        finishSuggest({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "ok",
        });
        await Promise.resolve();
    });

    expect(applyMove).toHaveBeenCalledTimes(2);
    expect(applyMove).toHaveBeenLastCalledWith(opening, "right");
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. ok");
});

test("a blocked manual move during auto play gap or capacity backoff keeps busy and preserves the loop", async () => {
    let seenBackoffShouldReport;
    suggestMove
        .mockResolvedValueOnce({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "first",
        })
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenBackoffShouldReport = options.shouldReportOutcome;
            return Promise.reject(
                new SuggestError("model busy", {
                    status: 429,
                    limitReason: LIMIT_CAPACITY,
                    retryAfter: 1,
                }),
            );
        })
        .mockResolvedValueOnce({
            move: "down",
            mode: "llm",
            source: "llm",
            reason: "second",
        });
    const afterFirst = [{ id: 1, row: 0, col: 3, value: 2 }];
    applyMove.mockImplementation((_tiles, direction) => {
        if (direction === "left") {
            return {
                moved: false,
                scoreGained: 0,
                visualTiles: afterFirst,
                resolvedTiles: afterFirst,
                lost: false,
            };
        }
        return {
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
            resolvedTiles: afterFirst,
            lost: false,
        };
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

    // Blocked key during auto_gap keeps Auto Play active and AI disabled.
    press("ArrowLeft");
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Right. first");

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    // Now inside auto_capacity_retry_wait; blocked key keeps backoff token and AI disabled.
    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    press("ArrowLeft");
    expect(seenBackoffShouldReport()).toBe(true);
    expect(screen.getByRole("button", { name: "Stop" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "AI" }).disabled).toBe(true);

    await act(async () => {
        vi.advanceTimersByTime(1000);
        await Promise.resolve();
    });

    expect(suggestMove).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status").textContent).toBe("Suggested: Down. second");
});

test("manual slide disables AI and Auto Play until settle completes", () => {
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 1, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 1, value: 2 }],
        lost: false,
    });

    render(<App />);
    expectStoppedControls({ status: null });

    press("ArrowRight");
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS - 1);
    });
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    act(() => {
        vi.advanceTimersByTime(1);
    });
    expectStoppedControls({ status: null });
});

test("a token-matched AbortError during manual Thinking returns silently to idle", async () => {
    let rejectSuggest;
    suggestMove.mockImplementation(
        () =>
            new Promise((_resolve, reject) => {
                rejectSuggest = reject;
            }),
    );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(screen.getByRole("button", { name: "Thinking…" }).disabled).toBe(true);

    await act(async () => {
        rejectSuggest(new DOMException("Aborted", "AbortError"));
        await Promise.resolve();
    });

    expectStoppedControls({ status: null });
    expect(applyMove).not.toHaveBeenCalled();
});

test("pending Play stays intact on a blocked manual move and clears on a valid manual move", async () => {
    suggestMove.mockResolvedValue({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "Opens space on the left.",
    });
    applyMove
        .mockReturnValueOnce({
            moved: false,
            scoreGained: 0,
            visualTiles: opening,
            resolvedTiles: opening,
            lost: false,
        })
        .mockReturnValueOnce({
            moved: true,
            scoreGained: 0,
            visualTiles: [{ id: 1, row: 3, col: 0, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
            resolvedTiles: [{ id: 1, row: 3, col: 0, value: 2 }],
            lost: false,
        });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    // Blocked manual move keeps Play + hint.
    press("ArrowLeft");
    expect(screen.getByRole("button", { name: "Play Right" }).disabled).toBe(false);
    expect(screen.getByRole("status").textContent).toBe(
        "Suggested: Right. Opens space on the left.",
    );

    // Valid manual move clears Play + hint immediately and returns cleanly after settle.
    press("ArrowDown");
    expectStoppedControls({ aiDisabled: true, autoDisabled: true, status: null });

    act(() => {
        vi.advanceTimersByTime(SETTLE_MS);
    });
    expectStoppedControls({ status: null });
});

test("pending Play clears immediately when asking AI again or starting a New Game", async () => {
    let finishSecondSuggest;
    suggestMove
        .mockResolvedValueOnce({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: "Opens space on the left.",
        })
        .mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finishSecondSuggest = resolve;
                }),
        );

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "AI" }));

    await act(async () => {
        await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "Play Right" })).toBeTruthy();

    // Asking AI again clears Play + hint on entering Thinking.
    fireEvent.click(screen.getByRole("button", { name: "AI" }));
    expect(screen.getByRole("button", { name: "Thinking…" }).disabled).toBe(true);
    expect(screen.queryByRole("button", { name: /Play / })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();

    await act(async () => {
        finishSecondSuggest({
            move: "up",
            mode: "llm",
            source: "llm",
            reason: "Moves up.",
        });
        await Promise.resolve();
    });

    expect(screen.getByRole("button", { name: "Play Up" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("Suggested: Up. Moves up.");

    // New Game clears Play + hint.
    fireEvent.click(screen.getByRole("button", { name: "New Game" }));
    expectStoppedControls({ status: null });
});

test("a swipe started before New Game does not move the new board on pointerUp", () => {
    createInitialTiles.mockReset();
    createInitialTiles.mockReturnValueOnce(opening).mockReturnValueOnce(restarted);
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 9, row: 2, col: 3, value: 8, fromRow: 2, fromCol: 2, sliding: true }],
        resolvedTiles: [{ id: 9, row: 2, col: 3, value: 8 }],
        lost: false,
    });

    render(<App />);
    const firstBoard = document.querySelector(".board");
    fireEvent.pointerDown(firstBoard, {
        clientX: 10,
        clientY: 40,
        pointerId: 1,
        button: 0,
        pointerType: "touch",
    });

    fireEvent.click(screen.getByRole("button", { name: "New Game" }));

    const secondBoard = document.querySelector(".board");
    expect(secondBoard).not.toBe(firstBoard);
    fireEvent.pointerUp(secondBoard, {
        clientX: 100,
        clientY: 40,
        pointerId: 1,
        pointerType: "touch",
    });

    expect(applyMove).not.toHaveBeenCalled();

    // A fresh swipe on the new board still works normally.
    fireEvent.pointerDown(secondBoard, {
        clientX: 10,
        clientY: 40,
        pointerId: 2,
        button: 0,
        pointerType: "touch",
    });
    fireEvent.pointerUp(secondBoard, {
        clientX: 100,
        clientY: 40,
        pointerId: 2,
        pointerType: "touch",
    });
    expect(applyMove).toHaveBeenCalledTimes(1);
    expect(applyMove).toHaveBeenCalledWith(restarted, "right");
});

test("AI mode fieldset stays disabled across Auto Play phases and ignores mode changes while running", async () => {
    let finishFirstSuggest;
    let seenSignal;
    suggestMove
        .mockImplementationOnce((_board, _mode, options = {}) => {
            seenSignal = options.signal;
            return new Promise((resolve) => {
                finishFirstSuggest = resolve;
            });
        })
        .mockRejectedValueOnce(
            new SuggestError("model busy", {
                status: 429,
                limitReason: LIMIT_CAPACITY,
                retryAfter: 1,
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
    expect(screen.getByRole("group", { name: "AI mode" }).disabled).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    // 1. auto_thinking: fieldset disabled and mode change is ignored even if fieldset disabled is bypassed.
    const fieldset = screen.getByRole("group", { name: "AI mode" });
    expect(fieldset.disabled).toBe(true);
    fieldset.disabled = false;
    fireEvent.click(screen.getByRole("radio", { name: "Expectimax" }));
    fieldset.disabled = true;
    expect(screen.getByRole("radio", { name: "LLM" }).checked).toBe(true);
    expect(seenSignal.aborted).toBe(false);

    await act(async () => {
        finishFirstSuggest({
            move: "right",
            mode: "llm",
            source: "llm",
            reason: null,
        });
        await Promise.resolve();
    });

    // 2. auto_sliding: fieldset disabled.
    expect(screen.getByRole("group", { name: "AI mode" }).disabled).toBe(true);

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS);
        await Promise.resolve();
    });

    // 3. auto_gap: fieldset disabled.
    expect(screen.getByRole("group", { name: "AI mode" }).disabled).toBe(true);

    await act(async () => {
        vi.advanceTimersByTime(AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    // 4. auto_retry_wait: fieldset disabled.
    expect(screen.getByRole("status").textContent).toBe(HINT_CAPACITY_RETRYING);
    expect(screen.getByRole("group", { name: "AI mode" }).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expectStoppedControls({ status: null });
});

test("fallback retry budget resets after a successful move and after New Game", async () => {
    const fallbackReply = {
        move: "left",
        mode: "llm",
        source: "fallback",
        reason: null,
    };
    for (let i = 0; i < AUTO_PLAY_FALLBACK_MAX_RETRIES; i += 1) {
        suggestMove.mockResolvedValueOnce(fallbackReply);
    }
    suggestMove.mockResolvedValueOnce({
        move: "right",
        mode: "llm",
        source: "llm",
        reason: "ok",
    });
    suggestMove.mockResolvedValue(fallbackReply);
    applyMove.mockReturnValue({
        moved: true,
        scoreGained: 0,
        visualTiles: [{ id: 1, row: 0, col: 3, value: 2, fromRow: 0, fromCol: 0, sliding: true }],
        resolvedTiles: [{ id: 1, row: 0, col: 3, value: 2 }],
        lost: false,
    });

    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));

    for (let attempt = 0; attempt < AUTO_PLAY_FALLBACK_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
        await act(async () => {
            vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
            await Promise.resolve();
        });
    }

    expect(applyMove).toHaveBeenCalledTimes(1);

    await act(async () => {
        vi.advanceTimersByTime(SETTLE_MS + AUTO_PLAY_GAP_MS);
        await Promise.resolve();
    });

    // Move 2 gets a full fallback retry budget; interrupt with New Game on the final backoff.
    for (let attempt = 0; attempt < AUTO_PLAY_FALLBACK_MAX_RETRIES; attempt += 1) {
        expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
        if (attempt === AUTO_PLAY_FALLBACK_MAX_RETRIES - 1) {
            fireEvent.click(screen.getByRole("button", { name: "New Game" }));
            expectStoppedControls({ status: null });
        } else {
            await act(async () => {
                vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
                await Promise.resolve();
            });
        }
    }

    // Starting Auto Play on the new game also gets a fresh fallback retry budget.
    fireEvent.click(screen.getByRole("button", { name: "Auto Play" }));
    for (let attempt = 0; attempt < AUTO_PLAY_FALLBACK_MAX_RETRIES; attempt += 1) {
        await act(async () => {
            await Promise.resolve();
        });
        expect(screen.getByRole("status").textContent).toBe(HINT_SUGGEST_RETRYING);
        await act(async () => {
            vi.advanceTimersByTime(AUTO_PLAY_FALLBACK_RETRY_MS);
            await Promise.resolve();
        });
    }
    await act(async () => {
        await Promise.resolve();
    });
    expectStoppedControls({ status: HINT_SUGGEST_FAILED });
});

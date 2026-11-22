import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { SLIDE_MS } from "../game";
import Board from "./Board.jsx";

// jsdom does not load the component CSS, so stacking and slide distance use the real file.
const boardCss = readFileSync(resolve(process.cwd(), "src/components/Board.css"), "utf8");

beforeEach(() => {
    const style = document.createElement("style");
    style.setAttribute("data-board-css", "true");
    style.textContent = boardCss;
    document.head.appendChild(style);
});

afterEach(() => {
    cleanup();
    document.head.querySelector("[data-board-css]")?.remove();
});

test("game over stays above the tile layer", () => {
    render(
        <Board
            tiles={[
                { id: 40, row: 0, col: 0, value: 2, sliding: true, absorbing: true },
                { id: 41, row: 0, col: 1, value: 8, sliding: true },
                { id: 42, row: 1, col: 1, value: 4 },
            ]}
            lost
            onSwipe={() => {}}
        />,
    );

    // The overlay sits beside the tile layer, so it covers every tile, including one drawn above its neighbors.
    const overlay = screen.getByText("Game over");
    const layer = document.querySelector(".tile-layer");
    const overlayZ = Number(getComputedStyle(overlay).zIndex);
    const layerZ = Number(getComputedStyle(layer).zIndex);
    const moving = [...document.querySelectorAll(".tile")].find((tile) => tile.textContent === "2");
    const sliding = [...document.querySelectorAll(".tile")].find((tile) => tile.textContent === "8");
    const parked = [...document.querySelectorAll(".tile")].find((tile) => tile.textContent === "4");

    expect(layer.contains(moving)).toBe(true);
    expect(overlay.parentElement).toBe(layer.parentElement);
    expect(getComputedStyle(layer).position).toBe("absolute");
    expect(getComputedStyle(overlay).position).toBe("absolute");
    expect(layerZ).toBe(1);
    expect(overlayZ).toBe(2);
    expect(Number(getComputedStyle(moving).zIndex)).toBe(3);
    expect(Number(getComputedStyle(sliding).zIndex)).toBe(2);
    expect(Number(getComputedStyle(parked).zIndex)).toBe(1);
});

test("you win overlay prefers win over game over", () => {
    render(
        <Board
            tiles={[{ id: 1, row: 0, col: 0, value: 2048 }]}
            lost
            won
            onSwipe={() => {}}
        />,
    );
    expect(screen.getByText("You win!")).toBeTruthy();
    expect(screen.queryByText("Game over")).toBeNull();
});

test("a tile starts on its old cell and slides to the new one", () => {
    let frame = null;
    // Hold the frame so the tile can be seen on its old cell, then on the new one.
    const raf = vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
        frame = callback;
        return 1;
    });

    try {
        render(
            <Board
                tiles={[{ id: 1, row: 0, col: 2, fromRow: 0, fromCol: 0, value: 2, sliding: true }]}
                lost={false}
                onSwipe={() => {}}
            />,
        );
        const at = (col, row) => {
            const step = "(var(--cell) + var(--gap))";
            const probe = document.createElement("div");
            probe.style.transform = `translate(calc(${col} * ${step}), calc(${row} * ${step}))`;
            return probe.style.transform;
        };
        const tile = document.querySelector(".tile");
        // The slide step is the same cell and gap the grid uses.
        expect(boardCss).toContain("grid-template-columns: repeat(var(--size), var(--cell))");
        expect(boardCss).toContain("gap: var(--gap)");
        expect(tile.style.transition).toBe("none");
        expect(tile.style.transform).toBe(at(0, 0));

        frame();
        expect(tile.style.transition).toBe(`transform ${SLIDE_MS}ms ease-in-out`);
        expect(tile.style.transform).toBe(at(2, 0));
    } finally {
        raf.mockRestore();
    }
});

function drag(board, { from, to, pointerId = 1, button = 0, pointerType = "touch" }) {
    fireEvent.pointerDown(board, {
        clientX: from[0],
        clientY: from[1],
        pointerId,
        button,
        pointerType,
    });
    fireEvent.pointerUp(board, {
        clientX: to[0],
        clientY: to[1],
        pointerId,
        button,
        pointerType,
    });
}

test("a long drag on the board is a swipe", () => {
    const swipes = [];
    const { container } = render(
        <Board
            tiles={[{ id: 1, row: 0, col: 0, value: 2 }]}
            lost={false}
            onSwipe={(direction) => swipes.push(direction)}
        />,
    );
    const board = container.querySelector(".board");

    // Only the downward drag qualifies. A short drag, a right-click, and a cancelled pointer do not.
    drag(board, { from: [20, 20], to: [20, 100] });
    drag(board, { from: [20, 20], to: [30, 20] });
    drag(board, { from: [20, 20], to: [120, 20], button: 2, pointerType: "mouse" });

    fireEvent.pointerDown(board, { clientX: 20, clientY: 20, pointerId: 2, button: 0, pointerType: "touch" });
    fireEvent.pointerCancel(board, { pointerId: 2 });
    fireEvent.pointerUp(board, { clientX: 120, clientY: 20, pointerId: 2, pointerType: "touch" });

    expect(swipes).toEqual(["down"]);
});

test("another pointer's release keeps the swipe that is still down", () => {
    const swipes = [];
    const { container } = render(
        <Board
            tiles={[{ id: 1, row: 0, col: 0, value: 2 }]}
            lost={false}
            onSwipe={(direction) => swipes.push(direction)}
        />,
    );
    const board = container.querySelector(".board");

    // Pointer 1 lifts while pointer 2 is still down. Only pointer 2's downward drag counts.
    fireEvent.pointerDown(board, { clientX: 20, clientY: 20, pointerId: 1, button: 0, pointerType: "touch" });
    fireEvent.pointerDown(board, { clientX: 40, clientY: 40, pointerId: 2, button: 0, pointerType: "touch" });
    fireEvent.pointerUp(board, { clientX: 140, clientY: 20, pointerId: 1, pointerType: "touch" });
    fireEvent.pointerUp(board, { clientX: 40, clientY: 140, pointerId: 2, pointerType: "touch" });

    expect(swipes).toEqual(["down"]);
});

test("a release outside the board still counts after the board captures the pointer", () => {
    const original = Element.prototype.setPointerCapture;
    // jsdom does not retarget pointerup to the element that captured the pointer. This stand-in does.
    Element.prototype.setPointerCapture = function capture(pointerId) {
        const element = this;
        const onUp = (event) => {
            if (event.pointerId !== pointerId || event.target === element) return;
            document.removeEventListener("pointerup", onUp, true);
            element.dispatchEvent(new PointerEvent("pointerup", {
                bubbles: true,
                cancelable: true,
                clientX: event.clientX,
                clientY: event.clientY,
                pointerId,
                button: 0,
                pointerType: "touch",
            }));
        };
        document.addEventListener("pointerup", onUp, true);
    };

    try {
        const swipes = [];
        const { container } = render(
            <Board
                tiles={[{ id: 1, row: 0, col: 0, value: 2 }]}
                lost={false}
                onSwipe={(direction) => swipes.push(direction)}
            />,
        );
        const board = container.querySelector(".board");
        fireEvent.pointerDown(board, { clientX: 20, clientY: 20, pointerId: 1, button: 0, pointerType: "touch" });
        fireEvent.pointerUp(document.body, { clientX: 140, clientY: 24, pointerId: 1, pointerType: "touch" });
        expect(swipes).toEqual(["right"]);
    } finally {
        Element.prototype.setPointerCapture = original;
    }
});

test("the overlay stays hidden while the game can still be played", () => {
    render(
        <Board
            tiles={[{ id: 1, row: 0, col: 0, value: 2 }]}
            lost={false}
            onSwipe={() => {}}
        />,
    );

    expect(screen.queryByText("Game over")).toBeNull();
});

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Board from "./Board.jsx";

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

test("a tile starts on its old cell and slides to the new one", () => {
    let frame = null;
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
        const step = "(100% + (100% * 12 / 90))";
        const at = (col, row) => {
            const probe = document.createElement("div");
            probe.style.transform = `translate(calc(${col} * ${step}), calc(${row} * ${step}))`;
            return probe.style.transform;
        };
        const tile = document.querySelector(".tile");
        expect(tile.style.transition).toBe("none");
        expect(tile.style.transform).toBe(at(0, 0));

        frame();
        expect(tile.style.transition).toBe("transform 140ms ease-in-out");
        expect(tile.style.transform).toBe(at(2, 0));
    } finally {
        raf.mockRestore();
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

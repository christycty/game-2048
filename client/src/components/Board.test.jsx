import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test } from "vitest";
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

test("game over covers tiles even when a tile id outranks the overlay", () => {
    render(
        <Board
            tiles={[
                { id: 40, row: 0, col: 0, value: 2 },
                { id: 41, row: 1, col: 1, value: 4 },
            ]}
            lost
            onSwipe={() => {}}
        />,
    );

    const overlay = screen.getByText("Game over");
    const layer = document.querySelector(".tile-layer");
    const overlayZ = Number(getComputedStyle(overlay).zIndex);
    const layerZ = Number(getComputedStyle(layer).zIndex);
    const tileZ = Math.max(
        ...[...document.querySelectorAll(".tile")].map((tile) => Number(getComputedStyle(tile).zIndex)),
    );

    expect(layerZ).toBeGreaterThan(0);
    expect(overlayZ).toBeGreaterThan(layerZ);
    expect(tileZ).toBe(41);
    // Tile ids keep climbing, so the overlay has to sit above the layer rather than above every id.
    expect(tileZ).toBeGreaterThan(overlayZ);
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

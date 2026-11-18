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

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import ScoreCard from "./ScoreCard.jsx";

afterEach(cleanup);

test("help opens and Escape closes it", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    fireEvent.click(screen.getByRole("button", { name: "How to play" }));
    expect(screen.getByText("Arrow keys or swipe")).toBeTruthy();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText("Arrow keys or swipe")).toBeNull();
});

test("a press outside the help closes it", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    fireEvent.click(screen.getByRole("button", { name: "How to play" }));
    expect(screen.getByText("Arrow keys or swipe")).toBeTruthy();

    fireEvent.pointerDown(document.body);
    expect(screen.queryByText("Arrow keys or swipe")).toBeNull();
});

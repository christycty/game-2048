import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import ScoreCard, { HELP_TEXT } from "./ScoreCard.jsx";

afterEach(cleanup);

test("help opens and Escape closes it", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    fireEvent.click(screen.getByRole("button", { name: "How to play" }));
    const help = screen.getByText(HELP_TEXT);
    expect(help).toBeTruthy();
    expect(help.textContent).toContain("Expectimax");
    expect(help.textContent).toContain("Auto Play");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText(HELP_TEXT)).toBeNull();
});

test("a press outside the help closes it", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    fireEvent.click(screen.getByRole("button", { name: "How to play" }));
    expect(screen.getByText(HELP_TEXT)).toBeTruthy();

    // This press is a later one. The click that opened the help has already finished.
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText(HELP_TEXT)).toBeNull();
});

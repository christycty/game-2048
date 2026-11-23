import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import ScoreCard, { HELP_TEXT } from "./ScoreCard.jsx";

afterEach(cleanup);

test("renders score and bestScore with help closed initially", () => {
    const { container } = render(<ScoreCard score={128} bestScore={2048} />);
    const cards = [...container.querySelectorAll(".scorecard")].map((card) => ({
        title: card.querySelector(".scorecard-title")?.textContent,
        value: card.querySelector(".scorecard-value")?.textContent,
    }));

    expect(cards).toEqual([
        { title: "SCORE", value: "128" },
        { title: "BEST", value: "2048" },
    ]);
    expect(screen.getByRole("button", { name: "How to play" }).getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(HELP_TEXT)).toBeNull();
});

test("help opens, ignores non-Escape keys, and Escape closes it", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    const button = screen.getByRole("button", { name: "How to play" });
    expect(button.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    const help = screen.getByText(HELP_TEXT);
    expect(help).toBeTruthy();
    expect(help.textContent).toContain("Expectimax");
    expect(help.textContent).toContain("Auto Play");

    fireEvent.keyDown(document, { key: "Enter" });
    fireEvent.keyDown(document, { key: "ArrowDown" });
    expect(screen.getByText(HELP_TEXT)).toBeTruthy();
    expect(button.getAttribute("aria-expanded")).toBe("true");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByText(HELP_TEXT)).toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
});

test("clicking the help button a second time closes help", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    const button = screen.getByRole("button", { name: "How to play" });

    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(HELP_TEXT)).toBeTruthy();

    fireEvent.click(button);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(HELP_TEXT)).toBeNull();
});

test("pressing inside help keeps it open while pressing outside closes it", () => {
    render(<ScoreCard score={0} bestScore={4} />);
    const button = screen.getByRole("button", { name: "How to play" });
    fireEvent.click(button);
    const help = screen.getByText(HELP_TEXT);
    expect(help.classList.contains("help-text")).toBe(true);

    fireEvent.pointerDown(help);
    fireEvent.click(help);
    expect(screen.getByText(HELP_TEXT)).toBeTruthy();
    expect(button.getAttribute("aria-expanded")).toBe("true");

    // This press is outside the help container, so help closes.
    fireEvent.pointerDown(document.body);
    expect(screen.queryByText(HELP_TEXT)).toBeNull();
    expect(button.getAttribute("aria-expanded")).toBe("false");
});

test("unmounting while help is open removes document listeners cleanly", () => {
    const addSpy = vi.spyOn(document, "addEventListener");
    const removeSpy = vi.spyOn(document, "removeEventListener");

    try {
        const { unmount } = render(<ScoreCard score={0} bestScore={4} />);
        fireEvent.click(screen.getByRole("button", { name: "How to play" }));

        const addedPointer = addSpy.mock.calls.find(([type]) => type === "pointerdown")?.[1];
        const addedKey = addSpy.mock.calls.find(([type]) => type === "keydown")?.[1];
        expect(typeof addedPointer).toBe("function");
        expect(typeof addedKey).toBe("function");

        unmount();

        expect(removeSpy).toHaveBeenCalledWith("pointerdown", addedPointer);
        expect(removeSpy).toHaveBeenCalledWith("keydown", addedKey);

        fireEvent.pointerDown(document.body);
        fireEvent.keyDown(document, { key: "Escape" });
    } finally {
        addSpy.mockRestore();
        removeSpy.mockRestore();
    }
});

"""Expectimax search for the next 2048 move.

Player nodes maximize. Chance nodes average over a random spawn: each empty cell
is equally likely, and the new tile is a 2 (90%) or a 4 (10%), matching the client.
A board with a tile ≥ 2048 is a hard win (matching the client), scored above any
non-winning living position.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import NamedTuple

from app.cancel import SuggestCancelled
from app.moves import DIRECTIONS, FALLBACK_ORDER, apply_move

Board = tuple[tuple[int, ...], ...]
# Tests inject a fake clock; production uses monotonic time.
_Clock = Callable[[], float]
_SIZE = 4
_TWO_PROB = 0.9
_FOUR_PROB = 0.1
_WIN_TILE = 2048
_GAME_OVER = -1_000_000.0  # worse than any living board
_GAME_WON = 1_000_000.0  # better than any non-winning living board
_FALLBACK_RANK = {direction: index for index, direction in enumerate(FALLBACK_ORDER)}
# Depth 3+ was too slow for /suggest; stay at 1–2 and cut on this wall budget.
_BUDGET_SECONDS = 0.5
_OPEN_BOARD_EMPTIES = 8  # ≥ this → depth 1; tighter boards → depth 2
# Leaf heuristic weights (tuned for shallow search, not tournament play).
_EMPTY_WEIGHT = 270.0
_MAX_TILE_WEIGHT = 20.0
_SMOOTHNESS_WEIGHT = 12.0
_MONOTONICITY_WEIGHT = 20.0
_CORNER_BONUS = 50.0
_REASON_LABEL = {"left": "Left", "right": "Right", "up": "Up", "down": "Down"}


class Choice(NamedTuple):
    move: str
    reason: str


class _TimeUp(Exception):
    """The suggestion budget ran out before this depth finished."""


class _SearchBroken(Exception):
    """Search hit a board state that should be unreachable."""


def choose_move(
    board: list[list[int]],
    *,
    depth: int | None = None,
    budget_seconds: float | None = None,
    clock: _Clock | None = None,
    cancel: threading.Event | None = None,
) -> Choice | None:
    """Best legal move and score line, or None if stuck / unscored / broken."""
    if cancel is not None and cancel.is_set():
        raise SuggestCancelled()

    root = _freeze(board)
    legal = _legal_directions(root)
    if not legal:
        return None

    now = clock or time.monotonic
    # depth set, no budget → one full search (deterministic for tests).
    if depth is not None and budget_seconds is None:
        try:
            move, scores = _best_at_depth(
                root, legal, depth, deadline=None, clock=now, cancel=cancel
            )
        except _SearchBroken:
            return None
        return Choice(move, _format_reason(scores))

    limit = _depth_for(root) if depth is None else depth
    seconds = _BUDGET_SECONDS if budget_seconds is None else budget_seconds
    deadline = now() + seconds
    # Keep only fully finished depths so partial scores never win.
    best: str | None = None
    scores: dict[str, float | None] | None = None
    try:
        for current in range(limit + 1):
            if cancel is not None and cancel.is_set():
                raise SuggestCancelled()
            best, scores = _best_at_depth(root, legal, current, deadline, now, cancel=cancel)
    except (_TimeUp, _SearchBroken):
        # Budget or an unreachable state mid-depth: keep the last finished depth.
        pass
    if scores is None or best is None:
        return None  # nothing finished; N/A means illegal, not unscored
    return Choice(best, _format_reason(scores))


def _format_reason(scores: dict[str, float | None]) -> str:
    parts: list[str] = []
    for direction in DIRECTIONS:
        value = scores[direction]
        shown = "N/A" if value is None else f"{value:.1f}"
        parts.append(f"{_REASON_LABEL[direction]} = {shown}")
    return "Score of each direction: " + ", ".join(parts)


def _depth_for(board: Board) -> int:
    # Open boards fan out on every empty; keep them shallow.
    if _empty_count(board) >= _OPEN_BOARD_EMPTIES:
        return 1
    return 2


def _best_at_depth(
    root: Board,
    legal: list[str],
    depth: int,
    deadline: float | None,
    clock: _Clock,
    cancel: threading.Event | None = None,
) -> tuple[str, dict[str, float | None]]:
    cache: dict[tuple[Board, int, bool], float] = {}
    scores: dict[str, float | None] = {direction: None for direction in DIRECTIONS}
    best_move = legal[0]
    best_score = -math.inf
    for direction in legal:
        _check(deadline, clock, cancel)
        score = _chance_value(_apply(root, direction), depth, cache, deadline, clock, cancel=cancel)
        scores[direction] = score
        if score > best_score:
            best_score = score
            best_move = direction
    return best_move, scores


def _check(
    deadline: float | None,
    clock: _Clock,
    cancel: threading.Event | None = None,
) -> None:
    if cancel is not None and cancel.is_set():
        raise SuggestCancelled()
    if deadline is not None and clock() >= deadline:
        raise _TimeUp


def _chance_value(
    board: Board,
    depth: int,
    cache: dict[tuple[Board, int, bool], float],
    deadline: float | None = None,
    clock: _Clock = time.monotonic,
    cancel: threading.Event | None = None,
) -> float:
    _check(deadline, clock, cancel)
    key = (board, depth, False)
    cached = cache.get(key)
    if cached is not None:
        return cached

    # Legal slides always leave ≥1 empty for the spawn.
    empties = _empty_cells(board)
    if not empties:
        raise _SearchBroken("chance node reached a full board")

    # Merge already created 2048: spawn cannot undo the win. Prefer sooner wins
    # via +depth so a one-ply 2048 beats a longer path that also reaches 2048.
    if _has_won(board):
        value = _GAME_WON + depth
        cache[key] = value
        return value

    total = 0.0
    weight = 1.0 / len(empties)
    for row, col in empties:
        for tile, prob in ((2, _TWO_PROB), (4, _FOUR_PROB)):
            spawned = _place(board, row, col, tile)
            total += (
                weight * prob * _max_value(spawned, depth, cache, deadline, clock, cancel=cancel)
            )
    cache[key] = total
    return total


def _max_value(
    board: Board,
    depth: int,
    cache: dict[tuple[Board, int, bool], float],
    deadline: float | None = None,
    clock: _Clock = time.monotonic,
    cancel: threading.Event | None = None,
) -> float:
    _check(deadline, clock, cancel)
    key = (board, depth, True)
    cached = cache.get(key)
    if cached is not None:
        return cached

    # Match client: reaching 2048 is a hard win (checked after the spawn that led here).
    if _has_won(board):
        value = _GAME_WON + depth
        cache[key] = value
        return value

    legal = _legal_directions(board)
    if not legal:
        value = _GAME_OVER
        cache[key] = value
        return value

    if depth == 0:
        value = _evaluate(board)
        cache[key] = value
        return value

    value = max(
        _chance_value(_apply(board, direction), depth - 1, cache, deadline, clock, cancel=cancel)
        for direction in legal
    )
    cache[key] = value
    return value


def _has_won(board: Board) -> bool:
    return any(cell >= _WIN_TILE for row in board for cell in row)


def _evaluate(board: Board) -> float:
    empty = _empty_count(board)
    max_tile = max(value for row in board for value in row)
    score = empty * _EMPTY_WEIGHT
    if max_tile:
        score += math.log2(max_tile) * _MAX_TILE_WEIGHT
    score += _smoothness(board)
    score += _monotonicity(board)
    corners = (board[0][0], board[0][3], board[3][0], board[3][3])
    if max_tile and max_tile in corners:
        score += _CORNER_BONUS
    return score


def _smoothness(board: Board) -> float:
    """Penalize large gaps between neighboring tiles (log scale)."""
    penalty = 0.0
    for row in range(_SIZE):
        for col in range(_SIZE):
            value = board[row][col]
            if not value:
                continue
            left = math.log2(value)
            if col + 1 < _SIZE and board[row][col + 1]:
                penalty -= abs(left - math.log2(board[row][col + 1]))
            if row + 1 < _SIZE and board[row + 1][col]:
                penalty -= abs(left - math.log2(board[row + 1][col]))
    return penalty * _SMOOTHNESS_WEIGHT


def _monotonicity(board: Board) -> float:
    """Reward the stronger of increasing vs decreasing on each axis."""
    # totals: row↓, row↑, col↓, col↑ (log gaps); take max per axis.
    totals = [0.0, 0.0, 0.0, 0.0]
    for row in range(_SIZE):
        for col in range(_SIZE - 1):
            left = board[row][col]
            right = board[row][col + 1]
            if not left or not right:
                continue
            a, b = math.log2(left), math.log2(right)
            if a > b:
                totals[0] += b - a
            else:
                totals[1] += a - b
    for col in range(_SIZE):
        for row in range(_SIZE - 1):
            upper = board[row][col]
            lower = board[row + 1][col]
            if not upper or not lower:
                continue
            a, b = math.log2(upper), math.log2(lower)
            if a > b:
                totals[2] += b - a
            else:
                totals[3] += a - b
    return _MONOTONICITY_WEIGHT * (max(totals[0], totals[1]) + max(totals[2], totals[3]))


def _legal_directions(board: Board) -> list[str]:
    legal = [direction for direction in DIRECTIONS if _apply(board, direction) != board]
    # Tie-break matches FALLBACK_ORDER (same as the old stub).
    return sorted(legal, key=_FALLBACK_RANK.__getitem__)


def _apply(board: Board, direction: str) -> Board:
    # Same slider as legal_moves — a second copy can drift from the API.
    moved = apply_move([list(row) for row in board], direction)
    return _freeze(moved)


def _empty_cells(board: Board) -> list[tuple[int, int]]:
    return [(row, col) for row in range(_SIZE) for col in range(_SIZE) if board[row][col] == 0]


def _empty_count(board: Board) -> int:
    return sum(1 for row in board for value in row if value == 0)


def _place(board: Board, row: int, col: int, value: int) -> Board:
    return tuple(
        tuple(value if (r == row and c == col) else cell for c, cell in enumerate(line))
        for r, line in enumerate(board)
    )


def _freeze(board: list[list[int]]) -> Board:
    return tuple(tuple(row) for row in board)

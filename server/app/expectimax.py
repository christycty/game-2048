"""Expectimax search for the next 2048 move.

Player nodes maximize. Chance nodes average over a random spawn: each empty cell
is equally likely, and the new tile is a 2 (90%) or a 4 (10%), matching the client.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

from app.moves import DIRECTIONS, FALLBACK_ORDER, apply_move

Board = tuple[tuple[int, ...], ...]
# Tests pass a fake clock so the budget can expire on the next read, without
# sleeping through a real timeout. Production omits it and uses monotonic time.
_Clock = Callable[[], float]
_SIZE = 4
_TWO_PROB = 0.9
_FOUR_PROB = 0.1
# Game-over leaves need a hard penalty so the search avoids trapping itself.
_GAME_OVER = -1_000_000.0
_FALLBACK_RANK = {direction: index for index, direction in enumerate(FALLBACK_ORDER)}
# Depth is extra plies after the root move, and each ply spawns on every empty cell.
# Depth 3+ held the suggestion request for seconds, so the request path stays at 1 or 2
# and still gives up once the budget is spent.
_BUDGET_SECONDS = 0.5


class _TimeUp(Exception):
    """The suggestion budget ran out before this depth finished."""


def choose_move(
    board: list[list[int]],
    *,
    depth: int | None = None,
    budget_seconds: float | None = None,
    clock: _Clock | None = None,
) -> str | None:
    """Return the best legal direction, or None when the board is stuck."""
    root = _freeze(board)
    legal = _legal_directions(root)
    if not legal:
        return None

    now = clock or time.monotonic
    # An explicit depth with no budget is one complete search. Tests use that
    # path so the result does not depend on how fast the machine is.
    if depth is not None and budget_seconds is None:
        return _best_at_depth(root, legal, depth, deadline=None, clock=now)

    limit = _depth_for(root) if depth is None else depth
    seconds = _BUDGET_SECONDS if budget_seconds is None else budget_seconds
    deadline = now() + seconds
    # Keep the last depth that finished. A cutoff mid-depth must not compare a
    # half-scored move with a fully scored one.
    best = legal[0]
    try:
        for current in range(limit + 1):
            best = _best_at_depth(root, legal, current, deadline, now)
    except _TimeUp:
        return best
    return best


def _depth_for(board: Board) -> int:
    # Open boards branch on every empty cell, so they get one ply. Tighter
    # boards can afford a second. Neither is deep enough to stall the request.
    if _empty_count(board) >= 8:
        return 1
    return 2


def _best_at_depth(
    root: Board,
    legal: list[str],
    depth: int,
    deadline: float | None,
    clock: _Clock,
) -> str:
    cache: dict[tuple[Board, int, bool], float] = {}
    best_move = legal[0]
    best_score = -math.inf
    for direction in legal:
        _check(deadline, clock)
        score = _chance_value(_apply(root, direction), depth, cache, deadline, clock)
        if score > best_score:
            best_score = score
            best_move = direction
    return best_move


def _check(deadline: float | None, clock: _Clock) -> None:
    # No deadline means the caller asked for a full search, so the clock stays unread.
    if deadline is not None and clock() >= deadline:
        raise _TimeUp


def _chance_value(
    board: Board,
    depth: int,
    cache: dict[tuple[Board, int, bool], float],
    deadline: float | None = None,
    clock: _Clock = time.monotonic,
) -> float:
    _check(deadline, clock)
    key = (board, depth, False)
    cached = cache.get(key)
    if cached is not None:
        return cached

    empties = _empty_cells(board)
    if not empties:
        # A move always frees or keeps an empty cell before spawn; still be defensive.
        value = _max_value(board, depth, cache, deadline, clock)
        cache[key] = value
        return value

    total = 0.0
    weight = 1.0 / len(empties)
    for row, col in empties:
        for tile, prob in ((2, _TWO_PROB), (4, _FOUR_PROB)):
            spawned = _place(board, row, col, tile)
            total += weight * prob * _max_value(spawned, depth, cache, deadline, clock)
    cache[key] = total
    return total


def _max_value(
    board: Board,
    depth: int,
    cache: dict[tuple[Board, int, bool], float],
    deadline: float | None = None,
    clock: _Clock = time.monotonic,
) -> float:
    _check(deadline, clock)
    key = (board, depth, True)
    cached = cache.get(key)
    if cached is not None:
        return cached

    legal = _legal_directions(board)
    if not legal:
        # Must beat a merely cramped living board, including at depth-0 leaves.
        value = _GAME_OVER
        cache[key] = value
        return value

    if depth == 0:
        value = _evaluate(board)
        cache[key] = value
        return value

    value = max(
        _chance_value(_apply(board, direction), depth - 1, cache, deadline, clock)
        for direction in legal
    )
    cache[key] = value
    return value


def _evaluate(board: Board) -> float:
    empty = _empty_count(board)
    max_tile = max(value for row in board for value in row)
    score = empty * 270.0
    if max_tile:
        score += math.log2(max_tile) * 20.0
    score += _smoothness(board)
    score += _monotonicity(board)
    # Keep the highest tile in a corner when possible.
    corners = (board[0][0], board[0][3], board[3][0], board[3][3])
    if max_tile and max_tile in corners:
        score += 50.0
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
    return penalty * 12.0


def _monotonicity(board: Board) -> float:
    """Reward rows and columns that rise or fall steadily."""
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
    return 20.0 * (max(totals[0], totals[1]) + max(totals[2], totals[3]))


def _legal_directions(board: Board) -> list[str]:
    legal = [direction for direction in DIRECTIONS if _apply(board, direction) != board]
    # Stable tie-break matches the previous stub's preferred order when scores equal.
    return sorted(legal, key=_FALLBACK_RANK.__getitem__)


def _apply(board: Board, direction: str) -> Board:
    # One slider for search and for legal_moves. A second copy can suggest a move
    # the rest of the API treats as illegal.
    moved = apply_move([list(row) for row in board], direction)
    return _freeze(moved)


def _empty_cells(board: Board) -> list[tuple[int, int]]:
    return [
        (row, col)
        for row in range(_SIZE)
        for col in range(_SIZE)
        if board[row][col] == 0
    ]


def _empty_count(board: Board) -> int:
    return sum(1 for row in board for value in row if value == 0)


def _place(board: Board, row: int, col: int, value: int) -> Board:
    return tuple(
        tuple(value if (r == row and c == col) else cell for c, cell in enumerate(line))
        for r, line in enumerate(board)
    )


def _freeze(board: list[list[int]]) -> Board:
    return tuple(tuple(row) for row in board)

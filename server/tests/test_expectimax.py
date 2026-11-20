import time

import pytest

from app.expectimax import (
    _BUDGET_SECONDS,
    _chance_value,
    _freeze,
    _SearchBroken,
    choose_move,
)
from app.moves import first_legal_move, legal_moves
from helpers import COLUMN_PAIR, SORTED_ROW


def test_only_legal_move_is_chosen() -> None:
    board = [
        [2, 4, 8, 16],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert legal_moves(board) == ["down"]
    assert choose_move(board).move == "down"


def test_keeps_a_monotonic_row_intact() -> None:
    assert first_legal_move(SORTED_ROW) == "up"
    assert choose_move(SORTED_ROW, depth=0).move == "right"
    assert choose_move(SORTED_ROW).move == "right"


def test_merges_a_column_instead_of_the_fallback_slide() -> None:
    assert first_legal_move(COLUMN_PAIR) == "left"
    assert choose_move(COLUMN_PAIR, depth=0).move in {"up", "down"}
    assert choose_move(COLUMN_PAIR, depth=2).move in {"up", "down"}
    assert choose_move(COLUMN_PAIR).move in {"up", "down"}


def test_spawn_chance_counts_a_four() -> None:
    # One spawn layer. Down wins when a new tile can be a 4. Treating every
    # spawn as a 2 prefers the fallback, left.
    board = [
        [2, 2, 0, 0],
        [4, 2, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert first_legal_move(board) == "left"
    assert choose_move(board, depth=0).move == "down"


def test_equal_scores_keep_the_earlier_fallback_direction() -> None:
    # Left and right merge the pair into mirror-image boards with the same
    # score. The earlier fallback direction wins; >= would return right.
    board = [
        [0, 2, 2, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert legal_moves(board) == ["left", "right", "down"]
    assert choose_move(board, depth=0).move == "left"


def test_request_depth_follows_how_open_the_board_is() -> None:
    # Empty cells are the chance-node branch. Thirteen empties stop after one
    # ply; four empties take a second. The budget is long so this checks the
    # depth limit, not the clock.
    open_board = [
        [0, 0, 0, 0],
        [0, 4, 2, 4],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    open_move = choose_move(open_board, budget_seconds=2).move
    assert open_move == choose_move(open_board, depth=1).move == "down"
    assert choose_move(open_board, depth=0).move != open_move
    assert choose_move(open_board, depth=2).move != open_move

    tight = [
        [0, 0, 0, 0],
        [2, 4, 4, 2],
        [2, 4, 8, 16],
        [32, 64, 128, 256],
    ]
    tight_move = choose_move(tight, budget_seconds=2).move
    assert tight_move == choose_move(tight, depth=2).move == "right"
    assert choose_move(tight, depth=1).move != tight_move


def test_a_cutoff_keeps_the_last_finished_depth() -> None:
    # Depth 0 wants up. Depth 1 wants down. Expiring on the first read of the
    # deeper search must keep up, not the fallback left and not a partial down.
    board = [
        [0, 0, 0, 0],
        [0, 4, 2, 4],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert first_legal_move(board) == "left"
    shallow = choose_move(board, depth=0).move
    assert shallow == "up"
    assert choose_move(board, depth=1).move == "down"

    reads = 0

    def running() -> float:
        nonlocal reads
        reads += 1
        return 0.0

    assert choose_move(board, depth=0, budget_seconds=1, clock=running).move == shallow

    seen = 0

    def expire_on_the_next_depth() -> float:
        nonlocal seen
        seen += 1
        if seen <= reads:
            return 0.0
        return 1.0

    kept = choose_move(board, depth=1, budget_seconds=0.5, clock=expire_on_the_next_depth).move
    assert kept == shallow


def test_cutoff_before_any_depth_returns_none() -> None:
    # Expiring before depth 0 finishes must not invent a score line where N/A
    # would mean "illegal". The suggester treats None as fallback.
    board = [
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    started = False

    def expire_before_depth_zero() -> float:
        nonlocal started
        if not started:
            started = True
            return 0.0
        return 1.0

    assert choose_move(board, budget_seconds=0.5, clock=expire_before_depth_zero) is None


def test_returns_none_when_the_board_is_stuck() -> None:
    board = [
        [2, 4, 8, 16],
        [32, 64, 128, 256],
        [512, 1024, 2048, 4096],
        [8192, 16384, 32768, 65536],
    ]
    assert choose_move(board) is None


def test_a_full_board_that_can_merge_is_not_lost() -> None:
    # The top pair can still merge. A lost board would return None.
    board = [
        [2, 2, 8, 16],
        [32, 64, 128, 256],
        [512, 1024, 2048, 4096],
        [8192, 16384, 32768, 65536],
    ]
    assert first_legal_move(board) == "left"
    assert choose_move(board).move == "right"


def test_a_max_tile_pair_merges_instead_of_sliding() -> None:
    board = [
        [0, 0, 0, 65536],
        [0, 0, 0, 65536],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert first_legal_move(board) == "left"
    assert choose_move(board, depth=0).move in {"up", "down"}


def test_choice_is_always_legal() -> None:
    board = [
        [2, 0, 2, 0],
        [0, 4, 0, 4],
        [8, 0, 8, 0],
        [0, 16, 0, 16],
    ]
    move = choose_move(board, depth=2).move
    assert move in legal_moves(board)


def test_production_path_stays_near_the_budget() -> None:
    # Seven empties take depth 2. The budget must cut the search before a
    # multi-second stall; leave headroom for a slow CI host.
    board = [
        [8, 0, 8, 0],
        [16, 0, 8, 512],
        [0, 0, 0, 16],
        [0, 16, 32, 64],
    ]
    assert sum(cell == 0 for row in board for cell in row) == 7
    started = time.perf_counter()
    move = choose_move(board).move
    elapsed = time.perf_counter() - started
    assert move in legal_moves(board)
    assert elapsed < _BUDGET_SECONDS + 0.5


def test_chance_node_rejects_a_full_board() -> None:
    full = _freeze(
        [
            [2, 4, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2048, 4096],
            [8192, 16384, 32768, 65536],
        ]
    )
    with pytest.raises(_SearchBroken, match="full board"):
        _chance_value(full, 0, {})


def test_full_board_at_a_chance_node_aborts_the_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Force the unreachable chance-node path through choose_move so the
    # request layer gets None and can fall back instead of a 500.
    board = [
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]

    def boom(_board, _depth, _cache, deadline=None, clock=None):
        raise _SearchBroken("chance node reached a full board")

    monkeypatch.setattr("app.expectimax._chance_value", boom)
    assert choose_move(board, depth=0) is None


def test_reason_lists_a_score_or_na_for_each_direction() -> None:
    # Only right and down change this board. Left and up stay N/A.
    board = [
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    choice = choose_move(board, depth=0)
    assert choice is not None
    assert choice.move == "right"
    assert choice.reason.startswith("Score of each direction: ")
    assert "Left = N/A" in choice.reason
    assert "Up = N/A" in choice.reason
    assert "Right = N/A" not in choice.reason
    assert "Down = N/A" not in choice.reason
    # Left, Right, Up, Down — same order the UI can echo.
    left_at = choice.reason.index("Left =")
    right_at = choice.reason.index("Right =")
    up_at = choice.reason.index("Up =")
    down_at = choice.reason.index("Down =")
    assert left_at < right_at < up_at < down_at

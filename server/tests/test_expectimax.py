import time

from app.expectimax import (
    _GAME_OVER,
    _depth_for,
    _evaluate,
    _freeze,
    _max_value,
    choose_move,
)
from app.moves import first_legal_move, legal_moves


def test_only_legal_move_is_chosen() -> None:
    board = [
        [2, 4, 8, 16],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert legal_moves(board) == ["down"]
    assert choose_move(board) == "down"


def test_prefers_merging_over_only_sliding() -> None:
    board = [
        [2, 2, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    # Left/right merge the pair; down only relocates them.
    assert choose_move(board, depth=2) in {"left", "right"}


def test_keeps_a_monotonic_row_intact() -> None:
    board = [
        [16, 8, 4, 2],
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert legal_moves(board) == ["right", "down"]
    # Down would smash the sorted top row; right only slides the lone 2.
    assert choose_move(board, depth=2) == "right"


# Left is the fallback and only slides the column. Up and down merge the 4s.
COLUMN_PAIR = [
    [0, 0, 0, 4],
    [0, 0, 0, 4],
    [0, 0, 0, 8],
    [0, 0, 0, 0],
]


def test_merges_a_column_instead_of_the_fallback_slide() -> None:
    assert first_legal_move(COLUMN_PAIR) == "left"
    assert choose_move(COLUMN_PAIR, depth=0) in {"up", "down"}
    assert choose_move(COLUMN_PAIR, depth=2) in {"up", "down"}
    assert choose_move(COLUMN_PAIR) in {"up", "down"}


def test_depth_stays_shallow_enough_for_a_request() -> None:
    def with_empties(empty: int) -> tuple[tuple[int, ...], ...]:
        cells = [2] * (16 - empty) + [0] * empty
        return _freeze([cells[index : index + 4] for index in range(0, 16, 4)])

    assert _depth_for(with_empties(15)) == 1
    assert _depth_for(with_empties(8)) == 1
    assert _depth_for(with_empties(7)) == 2
    assert _depth_for(with_empties(0)) == 2


def test_a_spent_budget_does_not_run_the_deep_search() -> None:
    # This endgame took several seconds at depth 4 before the cutoff.
    board = [
        [64, 32, 16, 8],
        [32, 16, 8, 4],
        [16, 8, 4, 2],
        [8, 4, 2, 0],
    ]

    def clock() -> float:
        # The first read arms the deadline. Every later read is already past it.
        clock.calls += 1
        return 0.0 if clock.calls == 1 else 1.0

    clock.calls = 0
    started = time.perf_counter()
    move = choose_move(board, depth=4, budget_seconds=0.05, clock=clock)
    elapsed = time.perf_counter() - started
    assert move in legal_moves(board)
    assert clock.calls < 100
    assert elapsed < 1


def test_returns_none_when_the_board_is_stuck() -> None:
    board = [
        [2, 4, 8, 16],
        [32, 64, 128, 256],
        [512, 1024, 2048, 4096],
        [8192, 16384, 32768, 65536],
    ]
    assert choose_move(board) is None


def test_choice_is_always_legal() -> None:
    board = [
        [2, 0, 2, 0],
        [0, 4, 0, 4],
        [8, 0, 8, 0],
        [0, 16, 0, 16],
    ]
    move = choose_move(board, depth=2)
    assert move in legal_moves(board)


def test_game_over_leaf_is_far_worse_than_a_cramped_living_board() -> None:
    stuck = _freeze(
        [
            [2, 4, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2048, 4096],
            [8192, 16384, 32768, 65536],
        ]
    )
    # Full board, but the adjacent 2s keep a merge available.
    living_full = _freeze(
        [
            [2, 2, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2048, 4096],
            [8192, 16384, 32768, 65536],
        ]
    )
    assert legal_moves([list(row) for row in stuck]) == []
    assert legal_moves([list(row) for row in living_full])
    assert _max_value(stuck, 0, {}) == _GAME_OVER
    assert _max_value(living_full, 0, {}) == _evaluate(living_full)
    assert _max_value(living_full, 0, {}) > _GAME_OVER / 2

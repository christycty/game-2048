from app.expectimax import _GAME_OVER, _evaluate, _freeze, _max_value, choose_move
from app.moves import legal_moves


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

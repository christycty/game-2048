import pytest

from app.expectimax import _chance_value, _freeze, choose_move
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
    assert choose_move(board) == "down"


def test_keeps_a_monotonic_row_intact() -> None:
    assert first_legal_move(SORTED_ROW) == "up"
    assert choose_move(SORTED_ROW, depth=0) == "right"
    assert choose_move(SORTED_ROW) == "right"


def test_merges_a_column_instead_of_the_fallback_slide() -> None:
    assert first_legal_move(COLUMN_PAIR) == "left"
    assert choose_move(COLUMN_PAIR, depth=0) in {"up", "down"}
    assert choose_move(COLUMN_PAIR, depth=2) in {"up", "down"}
    assert choose_move(COLUMN_PAIR) in {"up", "down"}


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
    assert choose_move(board, depth=0) == "down"


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
    assert choose_move(board, depth=0) == "left"


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
    open_move = choose_move(open_board, budget_seconds=2)
    assert open_move == choose_move(open_board, depth=1) == "down"
    assert choose_move(open_board, depth=0) != open_move
    assert choose_move(open_board, depth=2) != open_move

    tight = [
        [0, 0, 0, 0],
        [2, 4, 4, 2],
        [2, 4, 8, 16],
        [32, 64, 128, 256],
    ]
    tight_move = choose_move(tight, budget_seconds=2)
    assert tight_move == choose_move(tight, depth=2) == "right"
    assert choose_move(tight, depth=1) != tight_move


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
    shallow = choose_move(board, depth=0)
    assert shallow == "up"
    assert choose_move(board, depth=1) == "down"

    reads = 0

    def running() -> float:
        nonlocal reads
        reads += 1
        return 0.0

    assert choose_move(board, depth=0, budget_seconds=1, clock=running) == shallow

    seen = 0

    def expire_on_the_next_depth() -> float:
        nonlocal seen
        seen += 1
        if seen <= reads:
            return 0.0
        return 1.0

    kept = choose_move(board, depth=1, budget_seconds=0.5, clock=expire_on_the_next_depth)
    assert kept == shallow


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
    assert choose_move(board) == "right"


def test_a_max_tile_pair_merges_instead_of_sliding() -> None:
    board = [
        [0, 0, 0, 65536],
        [0, 0, 0, 65536],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert first_legal_move(board) == "left"
    assert choose_move(board, depth=0) in {"up", "down"}


def test_choice_is_always_legal() -> None:
    board = [
        [2, 0, 2, 0],
        [0, 4, 0, 4],
        [8, 0, 8, 0],
        [0, 16, 0, 16],
    ]
    move = choose_move(board, depth=2)
    assert move in legal_moves(board)


def test_chance_node_rejects_a_full_board() -> None:
    full = _freeze(
        [
            [2, 4, 8, 16],
            [32, 64, 128, 256],
            [512, 1024, 2048, 4096],
            [8192, 16384, 32768, 65536],
        ]
    )
    with pytest.raises(AssertionError, match="full board"):
        _chance_value(full, 0, {})

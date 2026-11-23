import pytest

from app.moves import apply_move, legal_moves

# Documented example board (null cells become 0 here).
EXAMPLE_S = [
    [0, 8, 2, 2],
    [4, 2, 0, 2],
    [0, 0, 0, 0],
    [0, 0, 0, 2],
]

EXAMPLE_DOWN = [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [0, 8, 0, 2],
    [4, 2, 2, 4],
]  # No published Down example; this board is derived by hand.


def test_left_merges_a_pair_once() -> None:
    board = [
        [2, 2, 2, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert apply_move(board, "left") == [
        [4, 2, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert "up" not in legal_moves(board)


def test_right_merges_the_pair_nearest_the_edge() -> None:
    board = [
        [2, 2, 2, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert apply_move(board, "right")[0] == [0, 0, 2, 4]


def test_down_merges_a_vertical_pair() -> None:
    board = [
        [2, 0, 0, 0],
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert apply_move(board, "down") == [
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [4, 0, 0, 0],
    ]


def test_three_vertical_tiles_merge_once_toward_the_edge() -> None:
    board = [
        [2, 0, 0, 0],
        [2, 0, 0, 0],
        [2, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert [row[0] for row in apply_move(board, "up")] == [4, 2, 0, 0]
    assert [row[0] for row in apply_move(board, "down")] == [0, 0, 2, 4]


def test_left_merges_each_pair_once_and_not_the_result() -> None:
    board = [
        [2, 2, 2, 2],
        [2, 2, 4, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    applied = apply_move(board, "left")
    assert applied[0] == [4, 4, 0, 0]
    assert applied[1] == [4, 4, 0, 0]


def test_up_merges_a_vertical_pair() -> None:
    board = [
        [2, 0, 0, 0],
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert apply_move(board, "up") == [
        [4, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]


def test_packed_unequal_row_does_not_move() -> None:
    board = [
        [2, 4, 8, 16],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert "left" not in legal_moves(board)
    assert "right" not in legal_moves(board)


def test_single_corner_tile_can_move_right_or_down() -> None:
    board = [
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert legal_moves(board) == ["right", "down"]


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        ("left", [[8, 4, 0, 0], [4, 4, 0, 0], [0, 0, 0, 0], [2, 0, 0, 0]]),
        ("right", [[0, 0, 8, 4], [0, 0, 4, 4], [0, 0, 0, 0], [0, 0, 0, 2]]),
        ("up", [[4, 8, 2, 4], [0, 2, 0, 2], [0, 0, 0, 0], [0, 0, 0, 0]]),
        ("down", EXAMPLE_DOWN),
    ],
)
def test_documented_move_examples(direction: str, expected: list[list[int]]) -> None:
    assert apply_move(EXAMPLE_S, direction) == expected


def test_documented_lose_board_has_no_legal_moves() -> None:
    board = [
        [2, 4, 2, 4],
        [4, 2, 4, 2],
        [2, 4, 2, 4],
        [4, 2, 4, 2],
    ]
    assert legal_moves(board) == []

from app.moves import _apply, legal_moves


def test_left_merges_a_pair_once() -> None:
    board = [
        [2, 2, 2, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert _apply(board, "left") == [
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
    assert _apply(board, "right")[0] == [0, 0, 2, 4]


def test_down_merges_a_vertical_pair() -> None:
    board = [
        [2, 0, 0, 0],
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert _apply(board, "down") == [
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
    assert [row[0] for row in _apply(board, "up")] == [4, 2, 0, 0]
    assert [row[0] for row in _apply(board, "down")] == [0, 0, 2, 4]


def test_left_merges_each_pair_once_and_not_the_result() -> None:
    board = [
        [2, 2, 2, 2],
        [2, 2, 4, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    applied = _apply(board, "left")
    assert applied[0] == [4, 4, 0, 0]
    assert applied[1] == [4, 4, 0, 0]


def test_up_merges_a_vertical_pair() -> None:
    board = [
        [2, 0, 0, 0],
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert _apply(board, "up") == [
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

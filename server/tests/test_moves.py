from app.moves import legal_moves


def test_left_merges_a_pair_once() -> None:
    board = [
        [2, 2, 2, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert "left" in legal_moves(board)
    assert "up" not in legal_moves(board)


def test_single_corner_tile_can_move_right_or_down() -> None:
    board = [
        [2, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
    ]
    assert legal_moves(board) == ["right", "down"]

"""Legal 2048 moves on a 4x4 grid of tile values (0 is empty)."""

DIRECTIONS = ("left", "right", "up", "down")
FALLBACK_ORDER = ("left", "up", "right", "down")


def legal_moves(board: list[list[int]]) -> list[str]:
    return [direction for direction in DIRECTIONS if _apply(board, direction) != board]


def first_legal_move(board: list[list[int]]) -> str | None:
    legal = set(legal_moves(board))
    for direction in FALLBACK_ORDER:
        if direction in legal:
            return direction
    return None


def _apply(board: list[list[int]], direction: str) -> list[list[int]]:
    if direction == "left":
        return [_slide_line(row) for row in board]
    if direction == "right":
        return [_slide_line(row[::-1])[::-1] for row in board]
    columns = list(zip(*board, strict=True))
    if direction == "up":
        slid = [_slide_line(list(column)) for column in columns]
    else:
        slid = [_slide_line(list(column)[::-1])[::-1] for column in columns]
    return [list(row) for row in zip(*slid, strict=True)]


def _slide_line(line: list[int]) -> list[int]:
    tiles = [value for value in line if value]
    merged: list[int] = []
    index = 0
    while index < len(tiles):
        if index + 1 < len(tiles) and tiles[index] == tiles[index + 1]:
            merged.append(tiles[index] * 2)
            index += 2
        else:
            merged.append(tiles[index])
            index += 1
    return merged + [0] * (len(line) - len(merged))

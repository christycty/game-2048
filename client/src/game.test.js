import assert from "node:assert/strict";
import test from "node:test";
import {
    applyMove,
    createInitialTiles,
    GRID_SIZE,
    hasMoves,
    hasWon,
    MAX_START_TILES,
    MIN_START_TILES,
    tilesToBoard,
} from "./game.js";

// One line of the array is one row of the board, from the top. A 0 is an empty cell.
function board(rows) {
    let id = 1;
    const tiles = [];
    rows.forEach((line, row) => {
        line.forEach((value, col) => {
            if (value) tiles.push({ id: id++, row, col, value });
        });
    });
    return tiles;
}

// Fails when two tiles sit on the same cell.
function assertNoOverlap(tiles) {
    const grid = Array.from({ length: GRID_SIZE }, () => Array(GRID_SIZE).fill(0));
    for (const tile of tiles) {
        assert.equal(grid[tile.row][tile.col], 0, `two tiles occupy ${tile.row},${tile.col}`);
        grid[tile.row][tile.col] = tile.value;
    }
}

// () => 0.5 spawns a 2. Empty cells in `expected` are the only places that spawn may land.
function expectMove(start, direction, expected, score) {
    const result = applyMove(board(start), direction, () => 0.5);
    assert.equal(result.moved, true, `${direction} should change the board`);
    assert.equal(result.scoreGained, score);
    // The picture during the slide has one tile for each tile that was already there. The new tile is not in it yet.
    assert.equal(
        result.visualTiles.length,
        start.flat().filter(Boolean).length,
        "the spawned tile appears after the slide",
    );

    assertNoOverlap(result.resolvedTiles);
    const spawned = result.resolvedTiles.filter((tile) => tile.isNew);
    assert.equal(spawned.length, 1, "a valid move spawns one tile");
    const spawn = spawned[0];
    assert.ok(spawn.value === 2 || spawn.value === 4, "spawn is a 2 or a 4");

    for (let row = 0; row < GRID_SIZE; row++) {
        for (let col = 0; col < GRID_SIZE; col++) {
            const occupant = result.resolvedTiles.find((tile) => tile.row === row && tile.col === col);
            if (expected[row][col]) {
                assert.equal(occupant?.value, expected[row][col], `${direction} at ${row},${col}`);
                assert.equal(occupant.isNew, false, `${direction} at ${row},${col} is not the spawn`);
            } else if (occupant) {
                assert.equal(occupant, spawn, `${direction} leaves only the spawn at ${row},${col}`);
            }
        }
    }

    assert.equal(result.lost, false, "a board with room left is not a loss");
    assert.equal(result.won, false, "a board without 2048 is not a win");
    // During the slide the numbers still add up to the board from before the move.
    const startSum = start.flat().reduce((sum, value) => sum + value, 0);
    const visualSum = result.visualTiles.reduce((sum, tile) => sum + tile.value, 0);
    assert.equal(visualSum, startSum, "sliding tiles still show the old numbers");

    const ids = result.visualTiles.map((tile) => tile.id);
    assert.equal(new Set(ids).size, ids.length, "visual tiles keep distinct ids");
    return result;
}

test("a new game deals a random count of distinct 2 tiles", () => {
    // () => 0 → count = MIN_START_TILES and always the first empty cell.
    const few = createInitialTiles(() => 0);
    assert.equal(few.length, MIN_START_TILES);
    assert.ok(few.every((tile) => tile.value === 2));
    assert.notDeepEqual([few[0].row, few[0].col], [few[1].row, few[1].col]);

    // () => 0.99 → count = MAX_START_TILES; cell picks still advance through empties.
    const many = createInitialTiles(() => 0.99);
    assert.equal(many.length, MAX_START_TILES);
    assert.ok(many.every((tile) => tile.value === 2));
    const cells = new Set(many.map((tile) => `${tile.row},${tile.col}`));
    assert.equal(cells.size, MAX_START_TILES);
});

test("tile ids come from the tiles in play, not from earlier games", () => {
    const empty = [0, 0, 0, 0];
    // Play a move first. The game after it must still number its tiles from 1.
    applyMove(board([[2, 0, 0, 0], empty, empty, empty]), "right", () => 0);
    const tiles = createInitialTiles(() => 0);
    assert.deepEqual(tiles.map((tile) => tile.id), [1, 2]);

    // Those two 2s combine toward the right, so the new tile is id 3.
    const moved = applyMove(tiles, "right", () => 0);
    const spawn = moved.resolvedTiles.find((tile) => tile.isNew);
    assert.equal(spawn.id, 3);
});

test("tiles slide and merge once in every direction", () => {
    const empty = [0, 0, 0, 0];
    // The last number is the score added by the combinations. The second left move combines across a gap.
    expectMove([[2, 2, 0, 0], empty, empty, empty], "left", [[4, 0, 0, 0], empty, empty, empty], 4);
    expectMove([[2, 0, 0, 2], empty, empty, empty], "left", [[4, 0, 0, 0], empty, empty, empty], 4);
    expectMove([[2, 0, 0, 2], empty, empty, empty], "right", [[0, 0, 0, 4], empty, empty, empty], 4);
    expectMove([[2, 0, 0, 0], empty, empty, [2, 0, 0, 0]], "down", [empty, empty, empty, [4, 0, 0, 0]], 4);
    expectMove([empty, empty, [2, 0, 0, 0], [2, 0, 0, 0]], "up", [[4, 0, 0, 0], empty, empty, empty], 4);
});

test("a tile slides without merging, including across the reversed scan", () => {
    const empty = [0, 0, 0, 0];
    expectMove([[2, 0, 0, 0], empty, empty, empty], "right", [[0, 0, 0, 2], empty, empty, empty], 0);
    // Up scans from the bottom, so this 2 is the first tile visited.
    expectMove([empty, empty, empty, [0, 0, 0, 2]], "up", [[0, 0, 0, 2], empty, empty, empty], 0);
});

test("a line of tiles merges once when the scan starts at the far side", () => {
    const empty = [0, 0, 0, 0];
    // Right and down look at the destination side first, so the pairs form on that side.
    expectMove([[2, 2, 2, 2], empty, empty, empty], "right", [[0, 0, 4, 4], empty, empty, empty], 8);
    expectMove([[2, 2, 2, 0], empty, empty, empty], "right", [[0, 0, 2, 4], empty, empty, empty], 4);
    expectMove(
        [[2, 0, 0, 0], [2, 0, 0, 0], [2, 0, 0, 0], [2, 0, 0, 0]],
        "down",
        [empty, empty, [4, 0, 0, 0], [4, 0, 0, 0]],
        8,
    );
});

test("a row of four 2s becomes two 4s and does not merge again", () => {
    const result = expectMove(
        [[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "left",
        [[4, 4, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        8,
    );
    // Both results are combinations, so both tiles are marked merged.
    assert.equal(result.resolvedTiles.filter((tile) => tile.isMerged).length, 2);
});

test("three 2s merge the leading pair and leave the third 2", () => {
    expectMove(
        [[2, 2, 2, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "left",
        [[4, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        4,
    );
});

test("a merged tile does not merge again on the same move", () => {
    // The new 8, made from the two 4s, must sit beside the old 8 and not combine with it.
    expectMove(
        [[4, 4, 8, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "left",
        [[8, 8, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        8,
    );
});

test("a blocked move does not spawn or change the score", () => {
    const start = board([[2, 4, 8, 16], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]);
    const result = applyMove(start, "left");
    assert.equal(result.moved, false);
    assert.equal(result.scoreGained, 0);
    // The same array comes back, so the board was not copied or changed.
    assert.equal(result.resolvedTiles, start);
});

test("a merge keeps the old numbers sliding into the result cell", () => {
    // The 2 on the right slides into the 2 on the left. That cell then shows 4.
    const result = applyMove(board([[2, 2, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]), "left");
    const absorbed = result.visualTiles.find((tile) => tile.absorbing);
    const survivor = result.resolvedTiles.find((tile) => tile.isMerged);

    assert.equal(absorbed.value, 2);
    assert.deepEqual([absorbed.fromRow, absorbed.fromCol], [0, 1]);
    assert.deepEqual([absorbed.row, absorbed.col], [0, 0]);
    assert.equal(survivor.value, 4);
    assert.deepEqual([survivor.row, survivor.col], [0, 0]);
});

test("hasMoves is false only when every cell is filled and nothing matches", () => {
    const full = [];
    let id = 1;
    for (let row = 0; row < GRID_SIZE; row++) {
        for (let col = 0; col < GRID_SIZE; col++) {
            // Alternating 2 and 4, so no two neighbors match.
            full.push({ id: id++, row, col, value: (row + col) % 2 === 0 ? 2 : 4 });
        }
    }
    assert.equal(hasMoves(full), false);

    // Make the second tile a 2 as well, matching the tile on its left.
    full[1].value = 2;
    assert.equal(hasMoves(full), true);
    // A missing tile is a gap, so a slide is still possible.
    assert.equal(hasMoves(full.slice(0, 15)), true);
});

test("hasMoves sees a vertical match on an otherwise stuck board", () => {
    const tiles = [];
    let id = 1;
    for (let row = 0; row < GRID_SIZE; row++) {
        for (let col = 0; col < GRID_SIZE; col++) {
            tiles.push({ id: id++, row, col, value: (row + col) % 2 === 0 ? 2 : 4 });
        }
    }
    // Break the sideways match, and make this tile match the 2 above it.
    tiles.find((tile) => tile.row === 1 && tile.col === 0).value = 2;
    tiles.find((tile) => tile.row === 1 && tile.col === 1).value = 8;
    assert.equal(hasMoves(tiles), true);
});

// Moving up leaves one empty cell at the bottom-right, beside two 4s.
// () => 0.5 spawns a 2 there and the game is lost. () => 0 spawns a 4 and it is not.
const almostFull = [
    [2, 4, 2, 4],
    [4, 2, 4, 8],
    [2, 4, 8, 0],
    [4, 2, 4, 4],
];

test("a spawn of 2 that fills the board with no matches is a loss", () => {
    const result = applyMove(board(almostFull), "up", () => 0.5);
    assert.equal(result.moved, true);
    assert.equal(result.scoreGained, 0);
    assert.equal(result.lost, true);
    assert.equal(result.won, false);
    assert.equal(result.resolvedTiles.length, GRID_SIZE * GRID_SIZE);
    const spawn = result.resolvedTiles.find((tile) => tile.isNew);
    assert.equal(spawn.value, 2);
    assert.deepEqual([spawn.row, spawn.col], [3, 3]);
    assert.equal(result.visualTiles.some((tile) => tile.isNew), false);
});

test("a spawn of 4 that matches a neighbor keeps the game going", () => {
    const result = applyMove(board(almostFull), "up", () => 0);
    const spawn = result.resolvedTiles.find((tile) => tile.isNew);
    assert.equal(spawn.value, 4);
    assert.deepEqual([spawn.row, spawn.col], [3, 3]);
    assert.equal(result.lost, false);
    assert.equal(result.won, false);
});

test("merging two 1024s wins", () => {
    const empty = [0, 0, 0, 0];
    const result = applyMove(
        board([[1024, 1024, 0, 0], empty, empty, empty]),
        "left",
        () => 0.5,
    );
    assert.equal(result.moved, true);
    assert.equal(result.scoreGained, 2048);
    assert.equal(result.won, true);
    assert.equal(result.lost, false);
    assert.equal(hasWon(result.resolvedTiles), true);
    assert.ok(result.resolvedTiles.some((tile) => tile.value === 2048 && tile.isMerged));
});

test("reaching 2048 wins even when the spawn leaves no moves", () => {
    // Left merges to 2048 and opens (0,3); spawn fills it → full board with no matches.
    const start = [
        [1024, 1024, 2, 4],
        [8, 16, 32, 64],
        [128, 256, 512, 8],
        [16, 32, 64, 128],
    ];
    const result = applyMove(board(start), "left", () => 0.5);
    assert.equal(result.moved, true);
    assert.equal(result.won, true);
    assert.equal(result.lost, false);
    assert.equal(hasMoves(result.resolvedTiles), false);
});

test("tilesToBoard fills empty cells with 0 for the suggestion API", () => {
    assert.deepEqual(tilesToBoard(board([[2, 0, 0, 4], [0, 0, 0, 0], [0, 0, 0, 0], [0, 8, 0, 0]])), [
        [2, 0, 0, 4],
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [0, 8, 0, 0],
    ]);
});

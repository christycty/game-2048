import assert from "node:assert/strict";
import test from "node:test";
import { applyMove, createInitialTiles, hasMoves } from "./game.js";

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

function gridOf(tiles) {
    const grid = Array.from({ length: 4 }, () => Array(4).fill(0));
    for (const tile of tiles) {
        assert.equal(grid[tile.row][tile.col], 0, `two tiles occupy ${tile.row},${tile.col}`);
        grid[tile.row][tile.col] = tile.value;
    }
    return grid;
}

function expectMove(start, direction, expected, score) {
    const result = applyMove(board(start), direction);
    assert.equal(result.moved, true, `${direction} should change the board`);
    assert.equal(result.scoreGained, score);
    assert.equal(
        result.visualTiles.length,
        start.flat().filter(Boolean).length,
        "the spawned tile appears after the slide",
    );

    gridOf(result.resolvedTiles);
    const spawn = result.resolvedTiles.find((tile) => expected[tile.row][tile.col] !== tile.value);
    assert.ok(spawn, "a valid move spawns one tile");
    assert.ok(spawn.value === 2 || spawn.value === 4, "spawn is a 2 or a 4");
    assert.equal(spawn.isNew, true);

    for (let row = 0; row < 4; row++) {
        for (let col = 0; col < 4; col++) {
            const occupant = result.resolvedTiles.find((tile) => tile.row === row && tile.col === col);
            if (expected[row][col]) {
                assert.equal(occupant?.value, expected[row][col], `${direction} at ${row},${col}`);
            } else if (occupant) {
                assert.equal(occupant, spawn, `${direction} leaves only the spawn at ${row},${col}`);
            }
        }
    }

    assert.equal(result.lost, false, "a board with room left is not a loss");
    const startSum = start.flat().reduce((sum, value) => sum + value, 0);
    const visualSum = result.visualTiles.reduce((sum, tile) => sum + tile.value, 0);
    assert.equal(visualSum, startSum, "sliding tiles still show the old numbers");

    const ids = result.visualTiles.map((tile) => tile.id);
    assert.equal(new Set(ids).size, ids.length, "visual tiles keep distinct ids");
    return result;
}

test("a new game starts with two different 2 tiles", () => {
    const tiles = createInitialTiles();
    assert.equal(tiles.length, 2);
    assert.deepEqual(tiles.map((tile) => tile.value), [2, 2]);
    assert.notDeepEqual([tiles[0].row, tiles[0].col], [tiles[1].row, tiles[1].col]);
});

test("tiles slide and merge once in every direction", () => {
    const empty = [0, 0, 0, 0];
    expectMove([[2, 2, 0, 0], empty, empty, empty], "left", [[4, 0, 0, 0], empty, empty, empty], 4);
    expectMove([[2, 0, 0, 2], empty, empty, empty], "right", [[0, 0, 0, 4], empty, empty, empty], 4);
    expectMove([[2, 0, 0, 0], empty, empty, [2, 0, 0, 0]], "down", [empty, empty, empty, [4, 0, 0, 0]], 4);
    expectMove([empty, empty, [2, 0, 0, 0], [2, 0, 0, 0]], "up", [[4, 0, 0, 0], empty, empty, empty], 4);
});

test("a tile slides without merging, including across the reversed scan", () => {
    const empty = [0, 0, 0, 0];
    expectMove([[2, 0, 0, 0], empty, empty, empty], "right", [[0, 0, 0, 2], empty, empty, empty], 0);
    expectMove([empty, empty, empty, [0, 0, 0, 2]], "up", [[0, 0, 0, 2], empty, empty, empty], 0);
    expectMove([[2, 0, 0, 2], empty, empty, empty], "left", [[4, 0, 0, 0], empty, empty, empty], 4);
});

test("a line of tiles merges once when the scan starts at the far side", () => {
    const empty = [0, 0, 0, 0];
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
    assert.equal(result.resolvedTiles, start);
});

test("a merge keeps the old numbers sliding into the result cell", () => {
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
    for (let row = 0; row < 4; row++) {
        for (let col = 0; col < 4; col++) {
            full.push({ id: id++, row, col, value: (row + col) % 2 === 0 ? 2 : 4 });
        }
    }
    assert.equal(hasMoves(full), false);

    full[1].value = 2;
    assert.equal(hasMoves(full), true);
    assert.equal(hasMoves(full.slice(0, 15)), true);
});

test("hasMoves sees a vertical match on an otherwise stuck board", () => {
    const tiles = [];
    let id = 1;
    for (let row = 0; row < 4; row++) {
        for (let col = 0; col < 4; col++) {
            tiles.push({ id: id++, row, col, value: (row + col) % 2 === 0 ? 2 : 4 });
        }
    }
    tiles.find((tile) => tile.row === 1 && tile.col === 0).value = 2;
    tiles.find((tile) => tile.row === 1 && tile.col === 1).value = 8;
    assert.equal(hasMoves(tiles), true);
});

test("a move that fills the board with no matches is a loss", () => {
    const start = board([
        [2, 4, 2, 4],
        [4, 2, 4, 8],
        [2, 4, 8, 0],
        [4, 2, 4, 4],
    ]);
    const random = Math.random;
    Math.random = () => 0.5;
    try {
        const result = applyMove(start, "up");
        assert.equal(result.moved, true);
        assert.equal(result.scoreGained, 0);
        assert.equal(result.lost, true);
        assert.equal(result.resolvedTiles.length, 16);
        const spawn = result.resolvedTiles.find((tile) => tile.isNew);
        assert.equal(spawn.value, 2);
        assert.deepEqual([spawn.row, spawn.col], [3, 3]);
        assert.equal(result.visualTiles.some((tile) => tile.isNew), false);
    } finally {
        Math.random = random;
    }
});

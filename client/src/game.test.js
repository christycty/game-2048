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
    assert.equal(result.lost, !hasMoves(result.resolvedTiles));

    const grid = gridOf(result.resolvedTiles);
    for (let row = 0; row < 4; row++) {
        for (let col = 0; col < 4; col++) {
            if (expected[row][col]) {
                assert.equal(grid[row][col], expected[row][col], `${direction} at ${row},${col}`);
            }
        }
    }

    const placed = expected.flat().filter(Boolean).length;
    assert.equal(result.resolvedTiles.length, placed + 1, "a valid move spawns one tile");
    const spawn = result.resolvedTiles.find((tile) => expected[tile.row][tile.col] !== tile.value);
    assert.ok(spawn.value === 2 || spawn.value === 4, "spawn is a 2 or a 4");

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

test("a row of four 2s becomes two 4s and does not merge again", () => {
    const result = expectMove(
        [[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        "left",
        [[4, 4, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        8,
    );
    assert.equal(result.resolvedTiles.filter((tile) => tile.value === 4).length, 2);
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

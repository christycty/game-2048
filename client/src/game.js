import getRandomInt from "./utils.js";

export const GRID_SIZE = 4;
export const GRID_COUNT = GRID_SIZE * GRID_SIZE;
export const SLIDE_MS = 140;

const DIRECTIONS = {
    left: { row: 0, col: -1 },
    right: { row: 0, col: 1 },
    up: { row: -1, col: 0 },
    down: { row: 1, col: 0 },
};

let nextTileId = 1;

function createTile(row, col, value) {
    return { id: nextTileId++, row, col, value };
}

function inBounds(row, col) {
    return row >= 0 && row < GRID_SIZE && col >= 0 && col < GRID_SIZE;
}

function buildTraversals(vector) {
    const rows = [0, 1, 2, 3];
    const cols = [0, 1, 2, 3];
    if (vector.row > 0) rows.reverse();
    if (vector.col > 0) cols.reverse();
    return { rows, cols };
}

function emptyCells(grid) {
    const cells = [];
    for (let row = 0; row < GRID_SIZE; row++) {
        for (let col = 0; col < GRID_SIZE; col++) {
            if (!grid[row][col]) cells.push({ row, col });
        }
    }
    return cells;
}

// values locks the spawned number (opening tiles are always 2).
// otherwise a move spawns a 2 most of the time and a 4 the rest.
function spawnTile(grid, values) {
    const open = emptyCells(grid);
    if (open.length === 0) return null;

    const spot = open[getRandomInt(open.length)];
    const value = values ? values[getRandomInt(values.length)] : (getRandomInt(10) === 0 ? 4 : 2);
    const tile = createTile(spot.row, spot.col, value);
    grid[spot.row][spot.col] = tile;
    return tile;
}

function blankGrid() {
    return Array.from({ length: GRID_SIZE }, () => Array(GRID_SIZE).fill(null));
}

export function createInitialTiles() {
    const grid = blankGrid();
    const first = spawnTile(grid, [2]);
    const second = spawnTile(grid, [2]);
    return [first, second].filter(Boolean);
}

export function hasMoves(tiles) {
    if (tiles.length < GRID_COUNT) return true;

    const grid = blankGrid();
    for (const tile of tiles) grid[tile.row][tile.col] = tile.value;

    for (let row = 0; row < GRID_SIZE; row++) {
        for (let col = 0; col < GRID_SIZE; col++) {
            const value = grid[row][col];
            if (col + 1 < GRID_SIZE && grid[row][col + 1] === value) return true;
            if (row + 1 < GRID_SIZE && grid[row + 1][col] === value) return true;
        }
    }
    return false;
}

function presentTile(tile, { value, isNew = false, isMerged = false, absorbing = false, sliding = false }) {
    return {
        id: tile.id,
        value,
        row: tile.row,
        col: tile.col,
        fromRow: tile.fromRow ?? tile.startRow ?? tile.row,
        fromCol: tile.fromCol ?? tile.startCol ?? tile.col,
        isNew,
        isMerged,
        absorbing,
        sliding,
    };
}

// Slide every tile as far as it can go. Equal values merge once per tile.
// visualTiles is what animates (old numbers, including tiles that get absorbed).
// resolvedTiles is the board after the slide finishes, including the spawned tile.
export function applyMove(tiles, direction) {
    const vector = DIRECTIONS[direction];
    if (!vector) {
        return { moved: false, scoreGained: 0, visualTiles: tiles, resolvedTiles: tiles, lost: false };
    }

    const grid = blankGrid();
    for (const tile of tiles) {
        grid[tile.row][tile.col] = {
            id: tile.id,
            value: tile.value,
            row: tile.row,
            col: tile.col,
            startRow: tile.row,
            startCol: tile.col,
            merged: false,
            pendingValue: null,
        };
    }

    const { rows, cols } = buildTraversals(vector);
    const absorbed = [];
    let moved = false;
    let scoreGained = 0;

    for (const row of rows) {
        for (const col of cols) {
            const tile = grid[row][col];
            if (!tile) continue;

            let destRow = row;
            let destCol = col;
            let nextRow = row + vector.row;
            let nextCol = col + vector.col;

            while (inBounds(nextRow, nextCol) && !grid[nextRow][nextCol]) {
                destRow = nextRow;
                destCol = nextCol;
                nextRow += vector.row;
                nextCol += vector.col;
            }

            const next = inBounds(nextRow, nextCol) ? grid[nextRow][nextCol] : null;

            if (next && next.value === tile.value && !next.merged) {
                grid[row][col] = null;
                next.merged = true;
                next.pendingValue = tile.value * 2;
                scoreGained += next.pendingValue;
                absorbed.push({
                    id: tile.id,
                    value: tile.value,
                    row: next.row,
                    col: next.col,
                    fromRow: tile.startRow,
                    fromCol: tile.startCol,
                });
                moved = true;
            } else if (destRow !== row || destCol !== col) {
                grid[row][col] = null;
                tile.row = destRow;
                tile.col = destCol;
                grid[destRow][destCol] = tile;
                moved = true;
            }
        }
    }

    if (!moved) {
        return { moved: false, scoreGained: 0, visualTiles: tiles, resolvedTiles: tiles, lost: false };
    }

    const survivors = grid.flat().filter(Boolean);

    const spawned = spawnTile(grid);

    const visualTiles = [
        ...survivors.map((tile) => presentTile(tile, {
            value: tile.value,
            sliding: tile.row !== tile.startRow || tile.col !== tile.startCol,
        })),
        ...absorbed.map((tile) => presentTile(tile, {
            value: tile.value,
            absorbing: true,
            sliding: true,
        })),
    ];

    const resolvedTiles = survivors.map((tile) => presentTile(tile, {
        value: tile.pendingValue ?? tile.value,
        isMerged: tile.pendingValue != null,
    }));

    if (spawned) {
        resolvedTiles.push(presentTile(spawned, { value: spawned.value, isNew: true }));
    }

    return {
        moved: true,
        scoreGained,
        visualTiles,
        resolvedTiles,
        lost: !hasMoves(resolvedTiles),
    };
}

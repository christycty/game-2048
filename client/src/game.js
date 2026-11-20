export const GRID_SIZE = 4;
export const GRID_COUNT = GRID_SIZE * GRID_SIZE;
export const SLIDE_MS = 140;
// The merged numbers replace the slide once the transition has painted its last frame.
export const SETTLE_MS = SLIDE_MS + 20;
// Pause after settle before the next Auto Play suggestion so the loop is watchable
// and does not burn the process rate limit as fast as the slide allows.
export const AUTO_PLAY_GAP_MS = 750;

// One step on the board. Row grows downward, column grows to the right.
const DIRECTIONS = {
    left: { row: 0, col: -1 },
    right: { row: 0, col: 1 },
    up: { row: -1, col: 0 },
    down: { row: 1, col: 0 },
};

function createTile(id, row, col, value) {
    return { id, row, col, value };
}

function inBounds(row, col) {
    return row >= 0 && row < GRID_SIZE && col >= 0 && col < GRID_SIZE;
}

// Check cells starting from the side the tiles move toward. A row of four 2s then becomes two 4s on that side, instead of one 8.
function buildTraversals(vector) {
    const rows = Array.from({ length: GRID_SIZE }, (_, index) => index);
    const cols = Array.from({ length: GRID_SIZE }, (_, index) => index);
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

function roll(random, count) {
    return Math.floor(random() * count);
}

// choices limits the spawn (opening tiles pass [2]); otherwise a 2, or a 4 one time in ten.
function spawnTile(grid, id, random, choices) {
    const open = emptyCells(grid);
    if (open.length === 0) return null;

    const spot = open[roll(random, open.length)];
    const value = choices ? choices[roll(random, choices.length)] : (roll(random, 10) === 0 ? 4 : 2);
    const tile = createTile(id, spot.row, spot.col, value);
    grid[spot.row][spot.col] = tile;
    return tile;
}

function blankGrid() {
    return Array.from({ length: GRID_SIZE }, () => Array(GRID_SIZE).fill(null));
}

// Highest id already on this board, plus one. A previous game does not affect it.
function nextTileId(tiles) {
    return tiles.reduce((max, tile) => Math.max(max, tile.id), 0) + 1;
}

// Two 2s on different empty cells. Every new game starts its ids at 1.
export function createInitialTiles(random = Math.random) {
    const grid = blankGrid();
    const first = spawnTile(grid, 1, random, [2]);
    const second = spawnTile(grid, 2, random, [2]);
    return [first, second].filter(Boolean);
}

// A gap means some tile can still slide. A full board can move only when neighbors match.
export function hasMoves(tiles) {
    if (tiles.length < GRID_COUNT) return true;

    const grid = blankGrid();
    for (const tile of tiles) grid[tile.row][tile.col] = tile.value;

    // Each pair is seen once, from its top or left cell.
    for (let row = 0; row < GRID_SIZE; row++) {
        for (let col = 0; col < GRID_SIZE; col++) {
            const value = grid[row][col];
            if (col + 1 < GRID_SIZE && grid[row][col + 1] === value) return true;
            if (row + 1 < GRID_SIZE && grid[row + 1][col] === value) return true;
        }
    }
    return false;
}

// The /suggest API takes a 4x4 of tile values, with 0 for an empty cell.
export function tilesToBoard(tiles) {
    const board = Array.from({ length: GRID_SIZE }, () => Array(GRID_SIZE).fill(0));
    for (const tile of tiles) board[tile.row][tile.col] = tile.value;
    return board;
}

// The shape the board renders. fromRow and fromCol are the cell the tile slides out of.
function presentTile(tile, { value, fromRow, fromCol, isNew = false, isMerged = false, absorbing = false, sliding = false }) {
    return {
        id: tile.id,
        value,
        row: tile.row,
        col: tile.col,
        fromRow,
        fromCol,
        isNew,
        isMerged,
        absorbing,
        sliding,
    };
}

// One move. Every tile slides until it stops, and two tiles with the same number combine once.
// visualTiles is what the player sees during the slide: the old numbers, including the tile that slides into a combination.
// resolvedTiles is the board after the slide, with the combined number and the new tile. Each tile still records the cell it left, so the slide is not played again.
export function applyMove(tiles, direction, random = Math.random) {
    const vector = DIRECTIONS[direction];
    if (!vector) {
        // An unknown direction leaves the same tiles in place.
        return { moved: false, scoreGained: 0, visualTiles: tiles, resolvedTiles: tiles, lost: false };
    }

    // Copy the tiles so this move does not change the caller's board.
    // startRow and startCol are where the slide begins. pendingValue is the number shown after a merge.
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

            // Slide through empty cells and stop on the last one.
            while (inBounds(nextRow, nextCol) && !grid[nextRow][nextCol]) {
                destRow = nextRow;
                destCol = nextCol;
                nextRow += vector.row;
                nextCol += vector.col;
            }

            const next = inBounds(nextRow, nextCol) ? grid[nextRow][nextCol] : null;

            // Merge into the tile already there. It keeps its old number until the slide ends.
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
            // No merge. Move this same tile into the furthest empty cell.
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
        // Nothing changed, so there is no spawn and no score.
        return { moved: false, scoreGained: 0, visualTiles: tiles, resolvedTiles: tiles, lost: false };
    }

    const survivors = grid.flat().filter(Boolean);
    // A move opens a cell, by a merge or by a slide, and the new tile lands there.
    const spawned = spawnTile(grid, nextTileId(tiles), random);

    // Survivors keep their old number while they travel. The absorbed tile slides into them.
    const visualTiles = [
        ...survivors.map((tile) => presentTile(tile, {
            value: tile.value,
            fromRow: tile.startRow,
            fromCol: tile.startCol,
            sliding: tile.row !== tile.startRow || tile.col !== tile.startCol,
        })),
        ...absorbed.map((tile) => presentTile(tile, {
            value: tile.value,
            fromRow: tile.fromRow,
            fromCol: tile.fromCol,
            absorbing: true,
            sliding: true,
        })),
    ];

    // Show the doubled number, and mark it so the board can pop that tile.
    const resolvedTiles = survivors.map((tile) => presentTile(tile, {
        value: tile.pendingValue ?? tile.value,
        fromRow: tile.startRow,
        fromCol: tile.startCol,
        isMerged: tile.pendingValue != null,
    }));

    // Left out of visualTiles, so the spawn appears only when the slide ends.
    if (spawned) {
        resolvedTiles.push(presentTile(spawned, {
            value: spawned.value,
            fromRow: spawned.row,
            fromCol: spawned.col,
            isNew: true,
        }));
    }

    return {
        moved: true,
        scoreGained,
        visualTiles,
        resolvedTiles,
        // Lost only when the board after the spawn has no move left.
        lost: !hasMoves(resolvedTiles),
    };
}

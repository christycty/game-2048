import getRandomInt from "./utils.js";

export const GRID_SIZE = 4;
export const GRID_COUNT = GRID_SIZE * GRID_SIZE;

// game logic
function spawnNewTile(boardState, validValues) {
    // TODO: block invalid case
    // if no empty grid left, bye

    // get list of which grids are empty, random choose upon them
    let emptyGridIndices = [];
    let emptyGridCount = 0;
    for (let gridIndex = 0; gridIndex < GRID_COUNT; gridIndex++) {
        if (!boardState[gridIndex]) {
            emptyGridIndices.push(gridIndex);
            emptyGridCount++;
        }
    }

    // random choose grid index to spawn a tile on
    let index = emptyGridIndices[getRandomInt(emptyGridCount)];
    console.log("chosen index", index);

    // TODO: spawn a random possible value
    boardState[index] = validValues[0];
}

function initializeGameState(setCurrentScore, setBoardState) {
    // set current score as 0
    setCurrentScore(0);

    // initialize empty board
    let boardState = Array(GRID_COUNT); // array of length 16

    // random spawn two 2s on the board
    spawnNewTile(boardState, [2]);
    spawnNewTile(boardState, [2]);

    console.log("board state:", boardState);

    // update the board state
    setBoardState(boardState);
}

export default initializeGameState;
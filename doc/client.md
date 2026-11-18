# Client

The playable 2048 board. A new game deals two 2s. Arrow keys and swipes slide and merge tiles. Score and best score update after each slide. The AI button is present and does nothing yet.

This describes the client on the `docs` branch, which tracks `main`.

## Run

From `client/`:

```bash
npm install
npm run dev       # Vite dev server
npm test          # Vitest for React components, then node:test for game.js and swipe.js
npm run lint      # oxlint
npm run build     # production bundle
```

Stack: React 19, Vite, plain JavaScript. The page title is 2048. The app mounts from `index.html` into `#root` through `src/main.jsx`.

## Layout

| Path | Role |
|---|---|
| `src/App.jsx` | Score, best score, tiles, loss. Owns input and the slide timer. |
| `src/game.js` | Board rules. Pure functions. No DOM. |
| `src/swipe.js` | Turns a pointer delta into a direction. |
| `src/api.js` | Placeholder for the suggestion request. No call is made. |
| `src/utils.js` | Unused `getRandomInt`. Moves pass `Math.random` in instead. |
| `src/components/Board.jsx` | Cells, sliding tiles, game-over overlay, pointer gestures. |
| `src/components/ScoreCard.jsx` | Title, help, SCORE, BEST. |
| `src/components/ActionPanel.jsx` | New Game, and a disabled AI button. |

## What the player sees

The column is at most 420px wide and shrinks with the viewport. Colors follow the usual 2048 palette: beige page, brown board, tiles from 2 through 2048, and one shared style for 4096 and above.

Top row: the title, a `?` that opens "Arrow keys or swipe", then SCORE and BEST. The help closes on Escape, a click outside it, or another press of `?`.

The board is a 4×4 grid. Empty cells stay fixed. Tiles sit in a layer above them and slide between cells. A new tile scales in. A merged tile pops. When the game is lost, a "Game over" overlay covers the board.

Bottom row: **New Game** starts over. **AI** is disabled until a suggestion request exists.

Best score lives in component state for the page session. A reload clears it. New Game clears the current score and the board, and keeps the best score.

## A move

`App` listens for arrow keys once. The board reports swipes through the same `handleMove`. Both paths are ignored while a slide is in progress or the game is lost. A direction that does not change the board returns immediately, so the next input is accepted.

`applyMove` returns two boards:

- `visualTiles` is what plays during the slide. Numbers are still the old values. The tile that slides into a merge is still there. The spawned tile is not.
- `resolvedTiles` is the board after the slide: doubled values, the spawn, and `lost` if that board has no move.

`App` renders `visualTiles` right away, then after `SETTLE_MS` swaps in `resolvedTiles`, adds `scoreGained`, and updates best score. `SETTLE_MS` is the slide duration plus 20ms so the last frame of the transition has painted. Input during that window is dropped. New Game increments a token so a settle callback from the previous game does not write into the new one.

The key listener is not re-bound when state changes. The latest board, score, loss flag, and animation flag are kept in refs so a keypress reads the current game.

## Rules (`game.js`)

The grid is 4×4. Row 0 is the top. Column 0 is the left.

`createInitialTiles` places two 2s on different empty cells. Their ids are 1 and 2. A later spawn takes one more than the highest id already on that board, so a new game does not continue the previous game's ids.

`applyMove(tiles, direction, random)`:

1. Copies the tiles. The caller's array is left alone.
2. Walks cells starting from the side the tiles move toward. A row of four 2s becomes two 4s, not one 8.
3. Each tile slides through empty cells. It merges into the next tile of the same value only if that tile has not merged yet this move. The score gained is the new value.
4. If nothing moved, there is no spawn and no score.
5. Otherwise one tile spawns on a random empty cell: a 2, or a 4 one time in ten. The opening deal passes `[2]` so both starting tiles are 2s.
6. The game is lost only when the board after the spawn has no empty cell and no equal neighbors.

`hasMoves` is true when any cell is empty, or when a horizontal or vertical neighbor matches. Each pair is checked once, from the top or left cell.

`random` defaults to `Math.random` and is an argument so tests can pin the spawn.

## Drawing the slide (`Board`)

Tile position is a CSS transform. One step is `var(--cell) + var(--gap)`, the same sizes the grid uses, so a resize does not leave the slide on a stale pixel distance. `--cell` and `--gap` scale with the board width (90 and 12 parts of a 420-wide board).

On each move, a tile is parked on `fromRow` / `fromCol` for one frame with transitions off, then animated to its destination over `SLIDE_MS` (140ms). React does not write `transform`, so a later render does not cancel that transition. A tile that stays in its cell is placed there with no animation.

Tiles are rendered in id order so a merge does not reorder DOM nodes mid-slide. The tile sliding into a merge paints above a tile that only changes cell.

A swipe starts on pointer down (left button only for a mouse), captures the pointer so a release outside the board still counts, and ends on pointer up for that same pointer. A release from a different pointer leaves the gesture alone. Pointer cancel drops it. `swipeDirection` ignores a drag shorter than 24px. The longer axis wins. When the distances match, the vertical axis wins.

`touch-action: none` on the board keeps the browser from scrolling the gesture away.

## Tests

- `src/game.test.js` covers the deal, ids, slides, single merges, blocked moves, spawn timing, and loss.
- `src/swipe.test.js` covers the threshold and axis choice.
- `src/App.test.jsx` covers score timing, shared swipe and key paths, best score across a new game, a cancelled slide, and a lost game ignoring input.
- `src/components/Board.test.jsx` covers the slide, overlay stacking, and pointer capture.
- `src/components/ScoreCard.test.jsx` covers opening and closing help.

## Not built yet

`api.js` only notes the intended call: send the board and an AI mode, receive a suggested move. The AI button stays disabled. There is no undo, no leaderboard, and no saved best score.

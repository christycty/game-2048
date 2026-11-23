# Client

The playable 2048 board. A new game deals a random count of 2s (1–16). Arrow keys and swipes slide and merge tiles. Score and best score update after each slide. Reaching 2048 is a hard win; no moves left is a loss. The AI control asks the suggestion API for a move; the player confirms with **Play**, or turns on **Auto Play** to apply suggestions in a loop.

Agent/implementer detail for the client. Human architecture overview: [../architecture.md](../architecture.md). Product rules: [prd.md](prd.md).

## Run

From `client/`:

```bash
npm install
npm run dev       # Vite on CLIENT_HOST_PORT (default 5173; reads repo-root .env)
npm test          # Vitest for React components, then node:test under src/game and src/suggest
npm run lint      # oxlint
npm run build     # production bundle
```

The page calls same-origin `/suggest` (and `/client-events` for fail / spend `rate_limit` / capacity `model_busy` / cancel beacons) by default. Vite proxies those paths to the API (`API_PROXY_TARGET`, or `http://127.0.0.1:${API_HOST_PORT:-8000}`). Set `VITE_API_BASE_URL` to an absolute origin only to bypass the proxy. CORS follows `CLIENT_HOST_PORT` for that case. See [runtime.md](runtime.md) for Compose, Docker, and worktree ports. Correlation: [telemetry.md](telemetry.md).

Stack: React 19, Vite, plain JavaScript. The page title is 2048. The app mounts from `index.html` into `#root` through `src/main.jsx`.

## Layout

| Path | Role |
|---|---|
| `src/App.jsx` | Score, best score, tiles, loss/win, busy, mode, pending hint. Wires hooks to `ActionPanel` / `Board`; owns `startGame` and derived `canSuggest` / `canApplySuggestion` / `canToggleAutoPlay`. |
| `src/hooks/useKeyboardMoves.js` | Arrow keys → move; unmount aborts in-flight suggest + bumps token. |
| `src/hooks/useSuggestSession.js` | Suggest token, abort, capacity retries, beacon gate, `handleSuggest`. |
| `src/hooks/useMoveController.js` | `handleMove`, settle `SETTLE_MS`, Auto Play gap → suggest. |
| `src/hooks/useAutoPlayController.js` | Toggle/stop, `autoApplyingRef`; shared failed-apply exit; busy release on Stop. |
| `src/game/game.js` | Board rules. Pure functions. No DOM. Includes `tilesToBoard` for the API. |
| `src/game/swipe.js` | Turns a pointer delta into a direction. |
| `src/suggest/api.js` | `POST /suggest` with W3C `traceparent` and optional `AbortSignal`; beacons fail / spend `rate_limit` / capacity `model_busy` to `/client-events` unless `shouldReportOutcome` is false (stale token). Classifies 429 via `X-Suggest-Limit` / detail onto `SuggestError.limitReason`. Abort / HTTP `499` beacons `cancel` (not fail) and throws `AbortError`. Throws `SuggestError` on network, HTTP, or unusable body. |
| `src/suggest/trace.js` | Hand-rolled W3C `traceparent` (no browser OTel SDK). |
| `src/suggest/suggestHints.js` | Pure 429/fallback hint copy + `capitalize` / `formatSuggestionHint`. |
| `src/components/Board.jsx` | Cells, sliding tiles, game-over overlay, pointer gestures. |
| `src/components/ScoreCard.jsx` | Title, help, SCORE, BEST. |
| `src/components/ActionPanel.jsx` | New Game, AI, Auto Play / Stop, mode radios, hint, confirm. |

## What the player sees

The column is at most 420px wide and shrinks with the viewport. Colors follow the usual 2048 palette: beige page, brown board, tiles from 2 through 2048, and one shared style for 4096 and above.

Top row: the title, a `?` that opens "Arrow keys or swipe", then SCORE and BEST. The help closes on Escape, a click outside it, or another press of `?`.

The board is a 4×4 grid. Empty cells stay fixed. Tiles sit in a layer above them and slide between cells. A new tile scales in. A merged tile pops. When the game is lost, a "Game over" overlay covers the board.

Bottom of the page:

- **New Game** starts over and stops Auto Play.
- **AI** requests a suggestion. While the request is in flight the label is **Thinking…** and the button is disabled. **AI** is also disabled while Auto Play is running.
- **Auto Play** starts the suggest → apply → settle → `AUTO_PLAY_GAP_MS` pause → suggest loop using the currently selected mode. While running the label is **Stop** and `aria-pressed` is true. **Stop** is always available during the loop.
- **AI mode** radios: **LLM** (default) or **Expectimax**. The fieldset is disabled while Auto Play is running (usable during Thinking so a mode switch can abort).
- A status line under the modes shows the result or an error. During Auto Play the latest hint stays visible through the slide and through the next Thinking request.
- **Play {Direction}** appears only after a usable suggestion when Auto Play is off. The move is not applied until the player presses it.

Best score lives in component state for the page session. A reload clears it. New Game clears the current score and the board, and keeps the best score. It also clears any pending suggestion and stops Auto Play.

## A move

`useKeyboardMoves` binds arrow keys once (mirrors `onMove` into a ref so the listener stays stable). The board reports swipes through the same `handleMove` from `useMoveController`. Both paths are ignored while a slide is in progress or the game is lost. A direction that does not change the board returns immediately, so the next input is accepted.

`applyMove` returns two boards:

- `visualTiles` is what plays during the slide. Numbers are still the old values. The tile that slides into a merge is still there. The spawned tile is not.
- `resolvedTiles` is the board after the slide: doubled values, the spawn, and `lost` if that board has no move.

`useMoveController` renders `visualTiles` right away, then after `SETTLE_MS` swaps in `resolvedTiles`, adds `scoreGained`, and updates best score. `SETTLE_MS` is the slide duration plus 20ms so the last frame of the transition has painted. Input during that window is dropped. New Game increments a move token so a settle callback from the previous game does not write into the new one.

Keyboard / async suggest / Auto Play keep board, score, loss/win, busy, and loop flags in refs (plus cross-hook refs for `stopAutoPlay` / `handleMove` / `handleSuggest` assigned after render) so a keypress or late timer reads the current game.

A board-changing move clears the pending suggestion. A manual (non–Auto Play) board-changing move also clears the hint. An Auto Play–applied move keeps the hint through the slide. A blocked move leaves pending state alone. A board-changing move while a suggestion request is still in flight aborts the fetch (`AbortSignal`) and drops the token so a late response cannot open **Play** or continue Auto Play. **Stop** during Thinking, a mode change during Thinking, **New Game**, and unmount do the same. An abort is silent (no failure hint). Mode radios stay usable during Thinking (so a switch can abort); they stay disabled while Auto Play is on.

A manual board-changing move while Auto Play is running stops Auto Play.

## AI suggestion

`canSuggest` is true when the game is not lost, nothing is busy (slide or in-flight request), Auto Play is off, and `hasMoves` is true. `canApplySuggestion` needs a pending move and the same not-lost / not-busy checks. `canToggleAutoPlay` is true while Auto Play is on (so **Stop** works), or when the game can start a loop (not lost, not busy, and either a pending move or `hasMoves`).

`useSuggestSession.handleSuggest` (hint strings from `suggestHints.js`):

1. Clears any previous pending move. Clears the hint only when Auto Play is off (Auto Play keeps the last hint through Thinking).
2. Calls `suggestMove(tilesToBoard(tiles), aiMode, { signal, shouldReportOutcome })` with an `AbortController` for this request; a stale token after abandon does not beacon fail/rate_limit/model_busy; abort beacons `cancel`.
3. If `source` is `"fallback"`, shows **AI could not suggest a move**, does not offer **Play**, and stops Auto Play. The fixed fallback order is not treated as a model choice.
4. On a usable body, shows `Suggested: {Move}.` plus the reason when present. If Auto Play is off, sets `pendingMove`. If Auto Play is on, applies the move immediately via `handleMoveRef` (marked as an auto-apply so the loop is not treated as a manual takeover). Resets capacity-retry count.
5. On capacity `429` (`limitReason === capacity`): during Auto Play, shows **Model busy. Retrying…**, waits `Retry-After` (default 1s), and retries up to `AUTO_PLAY_CAPACITY_MAX_RETRIES` (3); after exhaustion shows **Model busy. Wait a moment and try again.** and stops. Manual AI shows the busy hint without retrying. Does not offer **Play**.
6. On spend `429`, shows **Too many suggestions. Wait a moment and try again.**, does not offer **Play**, and stops Auto Play.
7. On other network or HTTP failure, shows the same error line as fallback and stops Auto Play.
8. On abort (`AbortError`), stays silent: no hint change from the failure path, no **Play**. A stale abort (token already bumped by Stop / move / New Game / mode / unmount) leaves cleanup to that caller. A token-matched abort (e.g. HTTP `499` without a local `abort()`) still stops Auto Play so the loop cannot stall on **Stop**.

After an Auto Play move settles, if Auto Play is still on and the game is not lost, `useMoveController` waits `AUTO_PLAY_GAP_MS` (750ms) then calls `handleSuggest` again (via `handleSuggestRef`). The gap keeps `busy` true so **AI** stays inactive through the pause; **Stop** (`useAutoPlayController`) clears that hold immediately when nothing else is in flight. Loss, **Stop**, **New Game**, a manual move, a blocked auto-applied move, spend 429, exhausted capacity retries, or an unusable suggestion ends the loop (including during the gap).

Changing the mode clears a pending suggestion and aborts an in-flight suggest when Thinking. Choosing the same mode again is a no-op. **Play {Direction}** calls `handleMove` with that direction, so confirm shares the swipe and key path. Starting Auto Play keeps the selected mode, applies a pending suggestion first when one exists, then continues the loop after settle.

The UI does not show the response `mode` or `source` fields beyond treating `"fallback"` as failure. Expectimax reasons are the server score line and appear in the same hint as LLM reasons.

## Rules (`game/game.js`)

The grid is 4×4. Row 0 is the top. Column 0 is the left.

`createInitialTiles` places a uniform random count of 2s (`MIN_START_TILES`..`MAX_START_TILES`, currently 1–16) on distinct empty cells. Ids start at 1. A later spawn takes one more than the highest id already on that board, so a new game does not continue the previous game's ids.

`applyMove(tiles, direction, random)`:

1. Copies the tiles. The caller's array is left alone.
2. Walks cells starting from the side the tiles move toward. A row of four 2s becomes two 4s, not one 8.
3. Each tile slides through empty cells. It merges into the next tile of the same value only if that tile has not merged yet this move. The score gained is the new value.
4. If nothing moved, there is no spawn and no score.
5. Otherwise one tile spawns on a random empty cell: a 2, or a 4 one time in ten. The opening deal passes `[2]` so starting tiles are only 2s.
6. After the spawn: `won` if any tile is ≥ 2048; else `lost` if there is no empty cell and no equal neighbors. Win beats lose.

`hasMoves` is true when any cell is empty, or when a horizontal or vertical neighbor matches. Each pair is checked once, from the top or left cell.

`hasWon` is true when any tile value is ≥ `WIN_TILE` (2048). Tests import `WIN_TILE` / `SWIPE_THRESHOLD` rather than repeating those numbers.

`tilesToBoard` builds the 4×4 value grid the API expects. Empty cells are `0`. Animation fields are dropped.

`AUTO_PLAY_GAP_MS` (750) pauses between settled Auto Play moves. `AUTO_PLAY_CAPACITY_MAX_RETRIES` (3) caps how many capacity-busy `429`s Auto Play will retry before stopping.

`random` defaults to `Math.random` and is an argument so tests can pin the spawn.

## Drawing the slide (`Board`)

Tile position is a CSS transform. One step is `var(--cell) + var(--gap)`, the same sizes the grid uses, so a resize does not leave the slide on a stale pixel distance. `--cell` and `--gap` scale with the board width (90 and 12 parts of a 420-wide board).

On each move, a tile is parked on `fromRow` / `fromCol` for one frame with transitions off, then animated to its destination over `SLIDE_MS` (140ms). React does not write `transform`, so a later render does not cancel that transition. A tile that stays in its cell is placed there with no animation.

Tiles are rendered in id order so a merge does not reorder DOM nodes mid-slide. The tile sliding into a merge paints above a tile that only changes cell.

A swipe starts on pointer down (left button only for a mouse), captures the pointer so a release outside the board still counts, and ends on pointer up for that same pointer. A release from a different pointer leaves the gesture alone. Pointer cancel drops it. `swipeDirection` ignores a drag shorter than `SWIPE_THRESHOLD` (24px). The longer axis wins. When the distances match, the vertical axis wins.

`touch-action: none` on the board keeps the browser from scrolling the gesture away.

## Tests

- `src/game/game.test.js` covers the deal, ids, slides, single merges, blocked moves, spawn timing, win, loss, and `tilesToBoard`.
- `src/game/swipe.test.js` covers the threshold and axis choice (asserts via shared `SWIPE_THRESHOLD`).
- `src/suggest/api.test.js` covers same-origin `/suggest` + `traceparent`, success body, `SuggestError` statuses including spend vs capacity 429 classification, fail/rate_limit/model_busy beacons, skipping those when `shouldReportOutcome` is false, re-checking that gate after the suggest await, abort paths beaconing `cancel` (including during `json()`, HTTP `499`, aborted-but-resolved, and when `shouldReportOutcome` is false), and preserving `AbortError`.
- `src/suggest/trace.test.js` covers W3C `traceparent` shape and retry when `getRandomValues` returns all zeros.
- `src/suggest/suggestHints.test.js` covers `capitalize`, `formatSuggestionHint`, and `hintForSuggestFailure` copy branches.
- `src/App.test.jsx` is the behavior contract for the hooks (not rewritten per hook): score timing, shared swipe and key paths, best score across a new game, a cancelled slide, a lost game ignoring input, suggest-then-confirm, Auto Play apply/gap/loop/stop (including Stop during the gap re-enabling AI, Stop during Thinking aborting the fetch, a token-matched AbortError during Thinking stopping the loop, and keeping the selected LLM mode), hint kept through the next Thinking step, pending-start and in-loop blocked apply, loss / spend 429 / capacity retry + exhaustion / New Game exits, fallback/manual takeover, mode selection (including mode change during Thinking aborting the fetch), fallback / rate-limit / failed requests, dropping a stale suggestion after a board-changing move (asserts `signal.aborted` and `shouldReportOutcome` flipping false), New Game during Thinking aborting the fetch, and unmount aborting an in-flight suggest.
- `src/components/Board.test.jsx` covers the slide, overlay stacking, and pointer capture.
- `src/components/ScoreCard.test.jsx` covers opening and closing help.

## Not built yet

There is no undo, no leaderboard, and no saved best score. The client does not surface `source` beyond treating `"fallback"` as an error. Help text still mentions only keys and swipe.

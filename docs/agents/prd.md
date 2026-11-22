# Product: 2048 with AI suggestions

A single-player 2048 game in the browser. The player slides tiles to merge matching numbers, tracks score, and can ask for an AI suggestion for the next move—then confirm it, ignore it, or turn on Auto Play to apply suggestions in a loop.

Product rules for implementers and agents. Human-oriented narrative: [../overview.md](../overview.md). Implementation detail: [client.md](client.md), [server.md](server.md), [runtime.md](runtime.md).

## Goals

1. Play a familiar 2048 game: start with two 2s, slide and merge, spawn after each successful move.
2. Keep the surface small: current score, best score for the session, and new game. No undo, accounts, or leaderboard.
3. Offer optional AI help: the player picks a suggestion style, asks for a move, sees the recommendation, and either confirms with **Play** or starts **Auto Play**.

## Who it is for

Someone who wants a local or self-hosted 2048 session with an optional coach. There is no multiplayer, login, or shared ranking.

## Core game

| Behavior | Detail |
|---|---|
| Board | 4×4 grid. |
| Start | Two tiles valued **2** appear on random empty cells. |
| Controls | Arrow keys or swipe on the board. |
| Slide | All tiles move as far as they can in that direction. |
| Merge | Two equal tiles that collide combine into one tile with double the value. Each tile merges at most once per move. Score increases by the new value. |
| After a successful move | One new tile appears on a random empty cell: usually a **2**, sometimes a **4**. A move that does not change the board does nothing. |
| Loss | No empty cell and no two equal neighbors can merge. The board shows game over. Input no longer moves tiles. |
| New Game | Clears the board and current score, deals a fresh start, keeps best score for this page session. |

Help on the page explains arrow keys or swipe. Best score is for the current browser session only; a reload resets it.

## Scoring

- **SCORE** is the sum of merge values in the current game.
- **BEST** is the highest SCORE reached since the page was loaded.
- Starting a new game does not lower BEST.

## AI suggestions

Suggestions are optional. The player always keeps control of the board: they can ignore a hint, stop Auto Play, or take a manual move at any time.

### Modes

| Mode | Product intent today |
|---|---|
| **LLM** (default) | Ask a language model for a legal next move and a short reason. |
| **Expectimax** | Ask for a move from depth-limited expectimax search. The hint lists a score for each direction (`N/A` when that slide is illegal). |

The player can switch modes before asking. Changing mode drops any suggestion that was waiting for confirmation. Mode radios are locked while Auto Play is running.

### Confirm flow

1. Player chooses a mode.
2. Player presses **AI**. While waiting, the control shows **Thinking…** and cannot be pressed again.
3. On success, the page shows the suggested direction and, when available, a short reason. A **Play {Direction}** control appears.
4. Nothing moves until the player presses **Play**, or until they ignore the suggestion and move themselves (keys/swipe). Taking their own move clears the pending suggestion.
5. If the suggestion cannot be used (service failure, or a fallback that is not treated as a real recommendation), the page says **AI could not suggest a move** and does not offer **Play**.
6. If the API rate-limits the request, the page says **Too many suggestions. Wait a moment and try again.** and does not offer **Play**.

AI is unavailable when the game is over, while a move animation is playing, while a request is already in flight, while Auto Play is running, or when the board has no legal move.

### Auto Play

1. Player presses **Auto Play**. The control becomes **Stop** (`aria-pressed` true). Auto Play uses the currently selected mode (**LLM** or **Expectimax**).
2. If a usable suggestion is already pending, Auto Play applies it immediately. Otherwise it requests one.
3. On a usable suggestion, the client applies the move without waiting for **Play**, keeps the hint visible during the slide, waits a short pause after the slide settles, then requests the next suggestion.
4. Auto Play stops when the player presses **Stop**, starts **New Game**, loses, takes a manual key/swipe move, or when a suggestion is unusable (fallback, rate limit, or transport failure). **Stop** (and other takeover paths) abort an in-flight suggest so the client does not wait on a late response and the server can cancel that run. Abort is silent (no failure hint). Fallback/transport shows **AI could not suggest a move**; rate limit shows **Too many suggestions. Wait a moment and try again.** The board is unchanged for that step.
5. Auto Play does not invent moves on a timer without asking the API. Each applied move comes from a fresh suggestion for the current board.

### Product rules for suggestions

- The API only returns a usable suggestion (`source` other than `fallback`) after server-side legality checks. The client offers **Play** or Auto Play applies from that response without re-validating the direction locally.
- The player is never forced to accept a suggestion or keep Auto Play running; Stop and manual moves always reclaim control.
- There are no user accounts; suggestions are not tied to identity or saved history.

## What we are not building (for now)

- Undo / redo
- Leaderboards or cloud-saved best scores
- Accounts, auth, or billing
- Multiplayer or shared rooms
- Deep tournament-strength search (expectimax stays shallow for a fast suggestion)
- Mobile app stores or native shells (browser only)

## Success criteria

A release matches this product when:

- A new visitor can start a game, move with keys or swipe, see score update, lose, and start over without confusion.
- Best score survives New Game within the same page load and resets on full reload.
- The player can request an LLM or Expectimax suggestion, read the reason when one is returned, confirm with **Play**, and see that move applied like any other move.
- The player can start **Auto Play** in the selected mode, watch usable suggestions apply in a loop, and stop with **Stop**, New Game, a manual move, loss, or a failed suggestion.
- A failed or unusable suggestion leaves the board unchanged and shows a clear failure message (including a distinct rate-limit message).
- Expectimax returns a legal search move with a per-direction score line the player can read.

## Open product decisions

- Whether expectimax should search deeper (or expose more of the heuristic) for stronger play.
- Whether best score should persist across reloads.
- Whether a future host should add auth or a public demo URL—rate limiting already bounds model spend; auth and a public URL are still out of scope.

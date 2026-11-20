# Product: 2048 with AI suggestions

A single-player 2048 game in the browser. The player slides tiles to merge matching numbers, tracks score, and can ask for an AI suggestion for the next move—then decide whether to take it.

Product rules for implementers and agents. Human-oriented narrative: [../overview.md](../overview.md). Implementation detail: [client.md](client.md), [server.md](server.md), [runtime.md](runtime.md).

## Goals

1. Play a familiar 2048 game: start with two 2s, slide and merge, spawn after each successful move.
2. Keep the surface small: current score, best score for the session, and new game. No undo, accounts, or leaderboard.
3. Offer optional AI help: the player picks a suggestion style, asks for a move, sees the recommendation, and confirms before anything is played.

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

Suggestions are optional. The player always keeps control of the board.

### Modes

| Mode | Product intent today |
|---|---|
| **LLM** (default) | Ask a language model for a legal next move and a short reason. |
| **Expectimax** | Ask for a move from a search-style strategy. On the current product, this path is a placeholder: it returns a simple deterministic legal move, not a real expectimax search. |

The player can switch modes before asking. Changing mode drops any suggestion that was waiting for confirmation.

### Flow

1. Player chooses a mode.
2. Player presses **AI**. While waiting, the control shows **Thinking…** and cannot be pressed again.
3. On success, the page shows the suggested direction and, when available, a short reason. A **Play {Direction}** control appears.
4. Nothing moves until the player presses **Play**, or until they ignore the suggestion and move themselves (keys/swipe). Taking their own move clears the pending suggestion.
5. If the suggestion cannot be used (service failure, or a fallback that is not treated as a real recommendation), the page says **AI could not suggest a move** and does not offer **Play**.

AI is unavailable when the game is over, while a move animation is playing, while a request is already in flight, or when the board has no legal move.

### Product rules for suggestions

- A suggestion must be a legal direction for the current board when it is offered for confirmation.
- The player is never forced to accept a suggestion.
- The product does not auto-play moves on a timer or after every turn.
- There are no user accounts; suggestions are not tied to identity or saved history.

## What we are not building (for now)

- Undo / redo
- Leaderboards or cloud-saved best scores
- Accounts, auth, or billing
- Multiplayer or shared rooms
- Auto-play or “watch the AI finish the game”
- A finished expectimax (or other search) strategy beyond the current placeholder
- Mobile app stores or native shells (browser only)

## Success criteria

A release matches this product when:

- A new visitor can start a game, move with keys or swipe, see score update, lose, and start over without confusion.
- Best score survives New Game within the same page load and resets on full reload.
- The player can request an LLM suggestion, read the reason when one is returned, confirm with **Play**, and see that move applied like any other move.
- A failed or unusable suggestion leaves the board unchanged and shows a clear failure message.
- Expectimax is selectable, but its placeholder behavior is understood as not yet a real search coach.

## Open product decisions

- Whether expectimax (or other modes) should become real strategies before calling the feature “multi-mode AI.”
- Whether best score should persist across reloads.
- Whether a future host should add rate limits, auth, or a public demo URL—none of that is part of the current product surface.

Goal: write a 2048 game with the following features
1. for tile spawning:
- generate two '2's at two random empty space initially
- generate a 2 or 4 at a random empty space after each valid move that changes the board.
2. only keep current score, best score, new game. no other features like undo or leaderboard.
3. a new AI suggestion feature that suggests the next step:
- implement the AI in server
- frontend would trigger an API call to the server that passes the current game state and AI mode, and server returns the suggested move
- I aim for multiple AI modes, but let's start with LLM first.


Client:
- vite + js set up configured. 
- game logic lives in game.js, UI lives in components, I expect API call for AI feature lives in api.js
- For PRs with visible UI changes, attach a screenshot to the PR summary (`gh pr edit --attach` / body markdown). Prefer one clear shot in the summary; do not also post the same image as a separate comment.
- Screenshot quality checklist before upload:
  - Capture a full desktop viewport (~800px wide or more), not a narrow phone-width strip.
  - Prefer a full-viewport capture. Avoid CDP `clip` / `captureBeyondViewport` crops — they can tile or duplicate UI.
  - Verify the image yourself: no repeated headers/buttons, nothing cut off mid-control, aspect ratio looks normal on GitHub.
  - Show the new UI state (e.g. mode selected + suggestion + confirm control), not only the default board.

Server:
- use Python for backend
- use good practices that include Pydantic, Opentelemetry for observabilty, create proper classes to interact with model

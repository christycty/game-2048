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

Server:
- use Python for backend
- use good practices that include Pydantic, Opentelemetry for observabilty, create proper classes to interact with model

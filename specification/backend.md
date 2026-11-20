# Goal and Main Feature
The backend server is responsible for generating AI suggestion of the next move based on the current game board. It shall support at least 2 modes: LLM and expectimax.

Client would send current game state, backend computes best move (up/down/left/right) and return to client.

# Technical Specification
## API
Apart from health check, it shall implement only endpoint for above purposes.

## Stack
Use Python FastAPI and Pydantic to define the objects and API request fields standard. 
Use Ollama models for LLM with structure output. Add output parsing, validation, fallback and retry systems. 
Expectimax uses depth-limited search with a chance node for the random spawn
(2 at 90%, 4 at 10%, uniform over empty cells).
Use Docker for the deployment, use proper environment variable, a dev vs prod set up. Construct necessary CIs for PRs with pre-commit formatting hooks, Docker build checks and tests execution. 

# Requirements and Best Practices
- Always write test cases that are meaningful, logical, clean and non-redundant

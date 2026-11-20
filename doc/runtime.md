# Runtime

Prod Compose publishes the client on loopback port 5173 and does not publish the API. The page requests `/suggest` on that same origin. Nginx in the client image forwards the path to the `prod` service on the Compose network.

The API allows 5 suggestions per 60 seconds for the whole process. The next call returns 429 with `Retry-After`. The limit is not per browser: in prod the only caller is nginx, and the cap exists to bound model time.

Ollama stays on the host. The API reaches it at `host.docker.internal:11434` unless `COMPOSE_OLLAMA_BASE_URL` is set. There is no login. The game has no accounts, and a key shipped in the page bundle would not be a credential.

Dev Compose still publishes the API on loopback port 8000 so a host process can call it. The dev client proxies `/suggest` to `http://dev:8000`. A Vite process on the host proxies to `http://127.0.0.1:8000`.

A later host would push the images CI already builds, pin the tags, terminate TLS at nginx, and leave the model on a private network.

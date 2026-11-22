import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Repo-root .env (Compose / worktree ports). Compose client-dev still forces
  // --port 5173 inside the container; only the host mapping moves.
  const env = loadEnv(mode, '..', '')
  const clientPort = Number(env.CLIENT_HOST_PORT || process.env.CLIENT_HOST_PORT || 5173)
  const apiPort = Number(env.API_HOST_PORT || process.env.API_HOST_PORT || 8000)

  return {
    plugins: [react()],
    server: {
      port: clientPort,
      strictPort: true,
      // Host dev proxies to uvicorn on the machine. Compose sets
      // API_PROXY_TARGET=http://dev:8000 so the client container reaches the API.
      proxy: {
        '/suggest': {
          target: process.env.API_PROXY_TARGET || `http://127.0.0.1:${apiPort}`,
        },
        '/client-events': {
          target: process.env.API_PROXY_TARGET || `http://127.0.0.1:${apiPort}`,
        },
      },
      watch: {
        usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
      },
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.jsx'],
    },
  }
})

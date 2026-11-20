import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Host dev proxies to uvicorn on the machine. Compose sets
    // API_PROXY_TARGET=http://dev:8000 so the client container reaches the API.
    proxy: {
      '/suggest': {
        target: process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000',
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
})

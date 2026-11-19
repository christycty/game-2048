import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
    },
  },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.jsx'],
  },
})

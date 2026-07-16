import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin API in dev: the frontend fetches /api/* and Vite forwards it
    // to the FastAPI/uvicorn backend. SSE (T-016) needs no buffering, so the
    // proxy stays untouched there too.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})

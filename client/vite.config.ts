/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom, not the browser: these tests cover the stateful logic a click-through
    // can't reliably reach — the resolve-body shapes, the 409 double-click race,
    // and the settle-on-stream-close path that has no terminal event. Visual and
    // real-EventSource behaviour is still the owner's browser session's job
    // (T-019/T-020); this is the net under the parts that bit us three times.
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
  },
  server: {
    // Same-origin API in dev: the frontend fetches /api/* and Vite forwards it
    // to the FastAPI/uvicorn backend. SSE (T-016) needs no buffering, so the
    // proxy stays untouched there too.
    proxy: {
      // MUST match the port in server/README.md (CLAUDE.md names that the
      // canonical run command). This said 8000 — uvicorn's default — while the
      // README has said 8137 since T-001, so every /api call from the browser
      // died on connection refused. Nothing caught it because the client and the
      // server had never been run at the same time until T-016 landed a UI.
      '/api': {
        target: 'http://localhost:8137',
        changeOrigin: true,
      },
    },
  },
})

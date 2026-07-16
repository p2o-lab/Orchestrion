import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Targets must be the literal 127.0.0.1, never `localhost`: on Windows
    // `localhost` resolves to ::1 (IPv6) first, and a uvicorn bound to 127.0.0.1
    // refuses that connection — ECONNREFUSED, observed on this project.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws':  { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})

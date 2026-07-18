import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Targets must be the literal 127.0.0.1, never `localhost`: on Windows
    // `localhost` resolves to ::1 (IPv6) first, and a uvicorn bound to 127.0.0.1
    // refuses that connection — ECONNREFUSED, observed on this project.
    //
    // ws:true so the live-state WebSocket (/api/peas/{id}/ws) upgrades through the
    // same /api prefix as the REST calls.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
    },
  },
})

import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// The Pi game loop's UI server (python pi/main.py --ui [--ui-port N]).
const API_TARGET = process.env.DELULU_API ?? 'http://127.0.0.1:8765'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
    },
  },
})

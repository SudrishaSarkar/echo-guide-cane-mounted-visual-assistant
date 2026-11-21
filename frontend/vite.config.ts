import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const BACKEND = 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Reachable from a phone on the same Wi-Fi, and through a tunnel.
    host: true,
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app', '.ngrok.app'],
    // The frontend uses relative URLs; forward backend paths to FastAPI.
    proxy: {
      '/api': BACKEND,
      '/action': BACKEND,
      '/video': BACKEND,
      '/ws': { target: BACKEND, ws: true },
    },
  },
})

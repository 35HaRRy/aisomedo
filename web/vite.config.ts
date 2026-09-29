import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Same-origin API in dev and prod: the browser only ever calls relative
  // paths. Dev Vite proxies them to the local backend; production Caddy
  // proxies them instead (no client-side origin config, no CORS).
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8000',
      '/pub': 'http://localhost:8000',
    },
  },
})

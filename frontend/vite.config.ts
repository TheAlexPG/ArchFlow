import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    watch: {
      // Polling keeps HMR reliable on WSL, VM, and bind-mounted/shared filesystems
      // where native file events can be dropped, causing updates only after refresh.
      usePolling: true,
      interval: 250,
    },
    proxy: {
      // /api/v1/ws/... is a WebSocket endpoint under the same /api prefix,
      // so we must enable ws here or the upgrade handshake dies at the proxy.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})

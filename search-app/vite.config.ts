import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const frontendPort = parseInt(process.env.SEARCH_FRONTEND_PORT || '3002', 10)
const backendPort = parseInt(process.env.SEARCH_BACKEND_PORT || '8092', 10)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: frontendPort,
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
      },
    },
  },
})

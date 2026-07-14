import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true },
      '/ws': { target: process.env.VITE_WS_TARGET || 'ws://localhost:8000', ws: true, changeOrigin: true },
      '/api/v1/ws': { target: process.env.VITE_WS_TARGET || 'ws://localhost:8000', ws: true, changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: { echarts: ['echarts'] },
      },
    },
  },
})

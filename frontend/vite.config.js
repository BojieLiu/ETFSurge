import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

export default defineConfig({
  plugins: [
    vue(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico'],
      manifest: {
        name: 'ETF Surge - 投资组合管理',
        short_name: 'ETFSurge',
        description: '多资产实时行情分析与 ETF 组合管理系统',
        theme_color: '#1a1a2e',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg,ico}'],
        runtimeCaching: [
          { urlPattern: /^\/api\//, handler: 'NetworkFirst', options: { cacheName: 'api-cache' } },
        ],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      // 注意顺序：更具体的路径在前，否则 /api 会先匹配 /api/v1/ws
      '/api/v1/ws': { target: process.env.VITE_WS_TARGET || 'ws://127.0.0.1:8000', ws: true, changeOrigin: true },
      '/ws': { target: process.env.VITE_WS_TARGET || 'ws://127.0.0.1:8000', ws: true, changeOrigin: true },
      '/api': { target: process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia', 'vue-echarts'],
          'vendor-axios': ['axios'],
          echarts: ['echarts'],
        },
      },
    },
  },
})

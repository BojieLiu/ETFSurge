import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'
import { visualizer } from 'rollup-plugin-visualizer'

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
    // E1+H: Bundle visualization + size budget (enabled via ANALYZE=true env var)
    ...(process.env.ANALYZE === 'true' ? [visualizer({
      filename: 'dist/stats.html',
      open: false,
      gzipSize: true,
      brotliSize: true,
    })] : []),
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
    // P2.3: Tree-shaking optimization — remove dead exports
    rollupOptions: {
      treeshake: {
        moduleSideEffects: false,
        propertyReadSideEffects: false,
        tryCatchDeoptimization: false,
      },
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          // P2.1: Remove full echarts from manualChunk — tree-shakable imports
          // used via echarts/core/echarts/charts/echarts/components
          'vendor-echarts': ['vue-echarts'],
          'vendor-axios': ['axios'],
          'vendor-marked': ['marked'],
        },
      },
    },
    // S10: Production optimizations
    minify: 'terser',
    terserOptions: {
      compress: { drop_console: true, drop_debugger: true },
    },
    // S10: Split CSS by entry for parallel loading (was false — single monolithic CSS)
    cssCodeSplit: true,
    sourcemap: false,
    // S10: Modulepreload strategy — generate preload hints for entry chunks
    modulePreload: { polyfill: false },
    // H: Bundle size budget — warn if any chunk exceeds thresholds
    chunkSizeWarningLimit: 700,
    assetsInlineLimit: 4096,
    reportCompressedSize: true,
  },
})

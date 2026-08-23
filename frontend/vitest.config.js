import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.spec.js'],
    css: false,
    // Coverage —— round36 工具链升级（2026-08-23）：默认 npm test 不跑覆盖率，
    // `npm run test:coverage` 显式启用（补齐 round35 §16「coverage 未开」的工具侧）。
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      reportsDirectory: 'coverage',
      include: ['src/**/*.{js,vue}'],
      exclude: ['src/test/**', 'src/mocks/**'],
    },
  },
})

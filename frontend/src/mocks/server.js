/**
 * MSW server —— round36 工具链升级（2026-08-23）
 * 供组件测试按需启用的请求拦截服务端。
 * 刻意不在 src/test/setup.js 全局启动：存量 ~500 用例行为保持不变，
 * 需要网络 mock 的测试自行 listen/reset/close（用法见 handlers.js 头注释）。
 */
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

export const server = setupServer(...handlers)

/**
 * MSW 默认 handlers —— round36 工具链升级（2026-08-23）
 *
 * 定位：契约即 mock。api-contracts/*.md 是前后端唯一事实源，
 * handler 从契约生成，组件测试不再逐个手写 vi.mock('../../api')。
 *
 * 用法（按需启用；刻意不进全局 setup.js，存量用例行为不变）：
 *   import { server } from '@/mocks/server'
 *   beforeAll(() => server.listen({ onUnhandledRequest: 'bypass' }))
 *   afterEach(() => server.resetHandlers())
 *   afterAll(() => server.close())
 *
 * 扩展流程：先在 api-contracts/ 写契约 → 在此补 handler → 组件测试直接受益。
 */
import { http, HttpResponse } from 'msw'

const BASE = '/api/v1'

/** 契约: api-contracts/market/search.md §2 —— 响应体统一结构（6 字段/条） */
export const handlers = [
  http.get(`${BASE}/market/search`, () =>
    HttpResponse.json([
      { symbol: '510300', name: '沪深300ETF', market: 'A', asset_type: 'etf', type: 'etf' },
      { symbol: '02800.HK', name: '盈富基金', market: 'HK', asset_type: 'HK', type: 'etf' },
      { symbol: 'SPY', name: 'SPDR S&P 500 ETF', market: 'US', asset_type: 'US', type: 'etf' },
    ]),
  ),
]

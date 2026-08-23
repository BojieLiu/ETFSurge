/**
 * MSW 安装健全性测试 —— round36 工具链升级（2026-08-23）
 * 只验证「拦截器能装上、请求能被接管」这一件事；
 * 业务 handler 示例见 src/mocks/handlers.js。
 */
import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '@/mocks/server'

describe('msw 骨架可用性', () => {
  it('setupServer 可启动并拦截运行时注册的请求', async () => {
    server.listen({ onUnhandledRequest: 'bypass' })
    server.use(
      http.get('https://unit-test.invalid/ping', () =>
        HttpResponse.json({ ok: true }),
      ),
    )
    try {
      const res = await fetch('https://unit-test.invalid/ping')
      expect(res.status).toBe(200)
      expect(await res.json()).toEqual({ ok: true })
    } finally {
      server.resetHandlers()
      server.close()
    }
  })
})

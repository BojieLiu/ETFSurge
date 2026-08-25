import { logger } from './logger'

/**
 * Round34 B4 / R110: 单飞 (single-flight) + 短 TTL 缓存工厂。
 *
 * 场景：多个组件/组合式函数在同一页面加载窗口内请求同一端点，旧实现并发
 * 触发 N 倍相同请求。本工具保证：
 * 1. 进行中的请求被复用（in-flight Promise 共享）；
 * 2. TTL 内的重复调用直接命中缓存结果（默认 30s）；
 * 3. 失败即清除缓存，下次调用可重试（不缓存错误）。
 *
 * 验收口径（round34 §10.2 B4）：Dashboard 单次加载 indices/global 请求数 ==1
 * （基线 ×3）、tasks ==1（基线 ×2）。
 */
export function createSingleFlight({ ttlMs = 30_000 } = {}) {
  const cache = new Map() // key -> { ts, promise, data }

  async function run(key, fetcher) {
    const now = Date.now()
    const hit = cache.get(key)
    if (hit) {
      if (hit.data !== undefined && now - hit.ts < ttlMs) return hit.data
      if (hit.promise) return hit.promise
    }
    const p = (async () => {
      try {
        const res = await fetcher()
        const data = res?.data ?? res
        cache.set(key, { ts: Date.now(), promise: null, data })
        return data
      } catch (e) {
        cache.delete(key)
        logger.warn(`[singleFlight] ${key} 上游失败，已清除缓存待重试:`, e?.message || e)
        throw e
      }
    })()
    cache.set(key, { ts: now, promise: p, data: undefined })
    return p
  }

  function invalidate(key) {
    if (key === undefined) cache.clear()
    else cache.delete(key)
  }

  return { run, invalidate }
}

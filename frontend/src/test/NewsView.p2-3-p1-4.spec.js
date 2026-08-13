import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => {
  let handler = null
  return {
    capture: (fn) => { handler = fn },
    getHandler: () => handler,
    reset: () => { handler = null },
  }
})

vi.mock('../composables/useNewsWS', () => ({
  useNewsWS: () => ({
    connected: { value: false },
    connect: vi.fn(),
    disconnect: vi.fn(),
    stop: vi.fn(),
    onNews: (fn) => h.capture(fn),
  }),
}))

const toastSpy = vi.hoisted(() => vi.fn())
vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: (...args) => toastSpy(...args) }),
}))

vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({
    etfs: [
      { symbol: '510050', name: '上证50ETF' },
      { symbol: '518880', name: '黄金ETF' },
    ],
  }),
}))

const apiMock = vi.hoisted(() => ({ headlines: vi.fn(), newsImpact: vi.fn() }))
vi.mock('../api', () => ({
  newsApi: {
    headlines: (...a) => apiMock.headlines(...a),
    newsImpact: (...a) => apiMock.newsImpact(...a),
  },
}))

const NewsView = (await import('../components/NewsView.vue')).default

describe('NewsView — P2-3 stars 新鲜度 + P1-4 ai_summary（round20）', () => {
  beforeEach(() => {
    h.reset()
    toastSpy.mockClear()
    apiMock.headlines.mockReset()
    apiMock.newsImpact.mockReset()
  })

  it('P2-3: 显示后端 stars 新鲜度（5★=<1h），与 level 徽章并存', async () => {
    // 后端 _compute_stars：<1h→5★；items 携带真实 stars 字段
    apiMock.headlines.mockResolvedValue({
      data: [
        { id: 1, title: '突发', content: 'c', level: 4, stars: 5, source: 'X', time: '10:00', ai_summary: null },
        { id: 2, title: '旧闻', content: 'c', level: 4, stars: 1, source: 'Y', time: '10:01', ai_summary: null },
      ],
    })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    const stars = wrapper.findAll('.news-stars')
    expect(stars.length).toBeGreaterThanOrEqual(2)
    // 第 1 条 level=4 但新鲜度 5★ → 显示 5（消费后端 stars，非 level 映射的 4）
    expect(stars[0].text()).toContain('5')
    // 第 2 条 stars=1 → 显示 1
    expect(stars[1].text()).toContain('1')
  })

  it('P1-4: ai_summary 非空时内联展示（消费后端预生成摘要）', async () => {
    apiMock.headlines.mockResolvedValue({
      data: [
        { id: 1, title: '突发', content: 'c', level: 5, stars: 5, source: 'X', time: '10:00',
          ai_summary: 'AI 生成的简要解读：政策利好推动板块上行。' },
        { id: 2, title: '无摘要', content: 'c', level: 2, stars: 3, source: 'Y', time: '10:01', ai_summary: null },
      ],
    })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('AI 生成的简要解读：政策利好推动板块上行。')
  })
})

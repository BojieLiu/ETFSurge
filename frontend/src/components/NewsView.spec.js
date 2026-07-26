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

const SAMPLE = [
  { id: 1, title: '重要利空', content: 'c1', level: 5, source: 'X', time: '10:00' },
  { id: 2, title: '普通新闻', content: 'c2', level: 2, source: 'Y', time: '10:01' },
]

describe('NewsView', () => {
  beforeEach(() => {
    h.reset()
    toastSpy.mockClear()
    apiMock.headlines.mockReset()
    apiMock.newsImpact.mockReset()
  })

  it('shows a toast for important items on enter', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    expect(toastSpy).toHaveBeenCalledWith(expect.stringContaining('重要利空'), 'warning')
  })

  it('does NOT toast for non-important-only batches', async () => {
    apiMock.headlines.mockResolvedValue({ data: [{ id: 9, title: '普通', level: 1 }] })
    mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('prepends a WS-pushed important item to the top of the list', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    h.getHandler()({ type: 'news', data: { id: 99, title: '突发推送', level: 5 } })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-item')
    expect(items.length).toBe(3)
    expect(wrapper.find('.news-title').text()).toBe('突发推送')
  })

  it('guards against duplicate WS items by id', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    const pushed = { id: 77, title: '重复推送', level: 5 }
    h.getHandler()({ type: 'news', data: pushed })
    h.getHandler()({ type: 'news', data: pushed })
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.news-item').length).toBe(1)
  })

  it('renders star rating characters for levels', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()
    // level 5 -> 4 stars, level 2 -> 2 stars
    expect(wrapper.text()).toContain('★★★★')
    expect(wrapper.text()).toContain('★★')
  })

  it('handles news_batch with multiple items in correct order', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    h.getHandler()({
      type: 'news_batch',
      data: [
        { id: 10, title: '最新新闻', time: '2026-07-26 15:30:00', sort_time: 1802410200, level: 3 },
        { id: 20, title: '稍早新闻', time: '2026-07-26 14:00:00', sort_time: 1802402400, level: 2 },
        { id: 30, title: '最早新闻', time: '2026-07-26 12:00:00', sort_time: 1802390400, level: 1 },
      ],
    })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-item')
    expect(items.length).toBe(3)
    // Should be sorted by sort_time descending (newest first)
    expect(items[0].text()).toContain('最新新闻')
    expect(items[1].text()).toContain('稍早新闻')
    expect(items[2].text()).toContain('最早新闻')
  })

  it('news_batch deduplicates by id', async () => {
    apiMock.headlines.mockResolvedValue({ data: [{ id: 1, title: '已有新闻', time: '10:00', level: 2 }] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    // Push batch that includes a duplicate id
    h.getHandler()({
      type: 'news_batch',
      data: [
        { id: 1, title: '已有新闻（重复）', time: '10:00', level: 2 },
        { id: 50, title: '全新新闻', time: '2026-07-26 16:00', sort_time: 1802412000, level: 3 },
      ],
    })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-item')
    // Only 2 items — the duplicate id:1 was not added
    expect(items.length).toBe(2)
  })

  it('news_batch with same sort_time preserves server order', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    // All items have the same sort_time — they stay in the order the server sent
    h.getHandler()({
      type: 'news_batch',
      data: [
        { id: 1, title: '第一条', time: '2026-07-26 15:30', sort_time: 1802410200, level: 2 },
        { id: 2, title: '第二条', time: '2026-07-26 15:30', sort_time: 1802410200, level: 2 },
      ],
    })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-title')
    // Same sort_time so stable: first item keeps first position
    expect(items[0].text()).toBe('第一条')
  })

  it('calls newsApi.newsImpact and shows the impact panel', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    apiMock.newsImpact.mockResolvedValue({
      data: {
        impact_scope: '全市场',
        summary: '偏负面',
        affected_holdings: [{ symbol: '510050', name: '上证50ETF', impact_reason: '承压' }],
      },
    })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    await wrapper.find('.news-ai-btn').trigger('click')
    await flushPromises()

    expect(apiMock.newsImpact).toHaveBeenCalled()
    expect(wrapper.find('.impact-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('全市场')
    expect(wrapper.text()).toContain('上证50ETF')
  })
})

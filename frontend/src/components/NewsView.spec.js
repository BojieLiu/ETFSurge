import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

let wsOptions = null

vi.mock('../composables/useNewsWS', () => ({
  useNewsWS: (opts) => {
    wsOptions = opts
    return { connected: { value: false }, connect: vi.fn(), disconnect: vi.fn() }
  },
}))

const toastSpy = vi.hoisted(() => vi.fn())
vi.mock('../stores/toast', () => ({ useToastStore: () => ({ show: (...args) => toastSpy(...args) }) }))

vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({
    etfs: [],
    all: [{ symbol: '510050' }, { symbol: '518880' }],
  }),
}))

const apiMock = vi.hoisted(() => ({ headlines: vi.fn(), newsImpact: vi.fn() }))
vi.mock('../api', () => ({
  newsApi: {
    headlines: (...a) => apiMock.headlines(...a),
    impact: (...a) => apiMock.newsImpact(...a),
  },
}))

const stubs = {
  AppCard: false,
  AppSkeleton: true,
  AppButton: false,
  AppBadge: false,
  PageHeader: { template: '<div><slot name="action" /><slot /></div>' },
  Section: { template: '<section><slot /></section>' },
}

const NewsView = (await import('../components/NewsView.vue')).default

const SAMPLE = [
  { id: 1, title: '重要利空', content: 'c1', level: 5, source: 'X', time: '10:00' },
  { id: 2, title: '普通新闻', content: 'c2', level: 2, source: 'Y', time: '10:01' },
]

describe('NewsView', () => {
  beforeEach(() => {
    wsOptions = null
    toastSpy.mockClear()
    apiMock.headlines.mockReset()
    apiMock.newsImpact.mockReset()
  })

  it('shows a toast for important items on enter', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    mount(NewsView, { global: { stubs } })
    await flushPromises()
    expect(toastSpy).toHaveBeenCalledWith(expect.objectContaining({ title: '重要利空', message: 'c1' }))
  })

  it('does NOT toast for non-important-only batches', async () => {
    apiMock.headlines.mockResolvedValue({ data: [{ id: 9, title: '普通', level: 1 }] })
    mount(NewsView, { global: { stubs } })
    await flushPromises()
    expect(toastSpy).not.toHaveBeenCalled()
  })

  it('prepends a WS-pushed important item to the top of the list', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    const wrapper = mount(NewsView, { global: { stubs } })
    await flushPromises()

    if (wsOptions && wsOptions.onMessage) {
      wsOptions.onMessage({ type: 'news', data: { id: 99, title: '突发推送', level: 5 } })
    }
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-item')
    expect(items.length).toBe(3)
    expect(wrapper.find('.news-title').text()).toBe('突发推送')
  })

  it('guards against duplicate WS items by id', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    const wrapper = mount(NewsView, { global: { stubs } })
    await flushPromises()

    const pushed = { id: 77, title: '重复推送', level: 5 }
    if (wsOptions && wsOptions.onMessage) {
      wsOptions.onMessage({ type: 'news', data: pushed })
      wsOptions.onMessage({ type: 'news', data: pushed })
    }
    await wrapper.vm.$nextTick()

    expect(wrapper.findAll('.news-item').length).toBe(1)
  })

  it('renders star rating characters for levels', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    const wrapper = mount(NewsView, { global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('★★★★')
    expect(wrapper.text()).toContain('★★')
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
    const wrapper = mount(NewsView, { global: { stubs } })
    await flushPromises()

    // Directly call analyze method instead of clicking (avoids event propagation issues)
    await wrapper.vm.analyze({ id: 1 })
    await flushPromises()

    expect(apiMock.newsImpact).toHaveBeenCalled()
    expect(wrapper.find('.impact-panel').exists()).toBe(true)
    expect(wrapper.find('.impact-panel').text()).toContain('偏负面')
  })
})

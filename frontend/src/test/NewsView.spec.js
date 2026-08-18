import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

// ── merged setup (Batch 5b S7.2 problem 3) ─────────────────────────────
// Originals: src/components/NewsView.spec.js (WS/toast/api mocks + F29/F31)
// and src/test/NewsView.spec.js (F2-8 inline analysis / R45 / R50). Both
// describe blocks are preserved; the hoisted mocks below satisfy both.

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
      { symbol: '510300', name: '沪深300ETF' },
      { symbol: '518880', name: '黄金ETF' },
    ],
  }),
}))

const apiMock = vi.hoisted(() => ({ headlines: vi.fn(), newsImpact: vi.fn(), macro: vi.fn(), globalNews: vi.fn(), stockNews: vi.fn(), research: vi.fn() }))
vi.mock('../api', () => ({
  newsApi: {
    headlines: apiMock.headlines,
    macro: apiMock.macro,
    globalNews: apiMock.globalNews,
    stockNews: apiMock.stockNews,
    research: apiMock.research,
    newsImpact: apiMock.newsImpact,
  },
}))

const NewsView = (await import('../components/NewsView.vue')).default
import { newsApi } from '../api'

// ---- shared fixtures from src/components/NewsView.spec.js ----
const SAMPLE = [
  { id: 1, title: '重要利空', content: 'c1', level: 5, source: 'X', time: '10:00' },
  { id: 2, title: '普通新闻', content: 'c2', level: 2, source: 'Y', time: '10:01' },
]

// ---- shared fixtures from src/test/NewsView.spec.js ----
const NEWS = [
  { id: 1, title: '央行降准释放流动性', content: '央行宣布下调存款准备金率。', level: 5, source: '财联社', time: '10:00' },
  { id: 2, title: '某地出台自然保护条例', content: '与金融市场无直接关联。', level: 2, source: '财联社', time: '09:00' },
]

function mountView() {
  return mount(NewsView)
}

async function mounted() {
  newsApi.headlines.mockResolvedValue({ data: NEWS })
  const wrapper = mountView()
  await flushPromises()
  return wrapper
}

const RESULT = {
  summary: '利好 A 股宽基',
  impact_scope: '市场整体',
  affected_holdings: [{ symbol: '510300', name: '沪深300ETF', impact_reason: '直接受益' }],
  disclaimer: '仅供参考',
}



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

  it('re-sorts after multiple legacy single-item WS pushes (prepend-reversal guard)', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    // Simulate original bug: 3 items pushed one-by-one via legacy 'news' type
    // Backend pushes newest first, but prepend would reverse without re-sort
    h.getHandler()({ type: 'news', data: { id: 1, title: '中', time: '10:02', sort_time: 1002, level: 2 } })
    h.getHandler()({ type: 'news', data: { id: 2, title: '新', time: '10:03', sort_time: 1003, level: 3 } })
    h.getHandler()({ type: 'news', data: { id: 3, title: '旧', time: '10:01', sort_time: 1001, level: 1 } })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-title')
    expect(items.length).toBe(3)
    // Must be sorted by sort_time descending: 新(1003) > 中(1002) > 旧(1001)
    expect(items[0].text()).toBe('新')
    expect(items[1].text()).toBe('中')
    expect(items[2].text()).toBe('旧')
  })

  it('re-sorts after mixed REST + WS merge', async () => {
    // REST loads old items
    apiMock.headlines.mockResolvedValue({ data: [
      { id: 1, title: 'REST旧', time: '2026-07-26 10:00', sort_time: 1000, level: 2 },
      { id: 2, title: 'REST更旧', time: '2026-07-26 09:00', sort_time: 900, level: 1 },
    ] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    // WS pushes newer items
    h.getHandler()({
      type: 'news_batch',
      data: [
        { id: 3, title: 'WS最新', time: '2026-07-26 11:00', sort_time: 1100, level: 3 },
        { id: 4, title: 'WS次新', time: '2026-07-26 10:30', sort_time: 1050, level: 2 },
      ],
    })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-title')
    expect(items.length).toBe(4)
    // Full list sorted: WS最新(1100) > WS次新(1050) > REST旧(1000) > REST更旧(900)
    expect(items[0].text()).toBe('WS最新')
    expect(items[1].text()).toBe('WS次新')
    expect(items[2].text()).toBe('REST旧')
    expect(items[3].text()).toBe('REST更旧')
  })

  it('sorts by time string when sort_time is missing', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    h.getHandler()({
      type: 'news_batch',
      data: [
        { id: 1, title: '较早', time: '2026-07-26 09:00', level: 1 },
        { id: 2, title: '较晚', time: '2026-07-26 10:00', level: 2 },
        { id: 3, title: '最早', time: '2026-07-26 08:00', level: 1 },
      ],
    })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-title')
    expect(items.length).toBe(3)
    // Fallback to time string: 较晚 > 较早 > 最早
    expect(items[0].text()).toBe('较晚')
    expect(items[1].text()).toBe('较早')
    expect(items[2].text()).toBe('最早')
  })

  it('calls newsApi.newsImpact and shows the impact inline (F2-8)', async () => {
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
    // F2-8: 结果展示在该条卡片内的行内展开区（不再有页面底部面板）
    expect(wrapper.find('.impact-panel').exists()).toBe(false)
    expect(wrapper.find('.impact-inline').exists()).toBe(true)
    expect(wrapper.text()).toContain('全市场')
    expect(wrapper.text()).toContain('上证50ETF')
  })

  // ── F29 (round23 §2.4 A4): 资讯分类 tab ──
  it('renders five news category tabs (F29)', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    const tabs = wrapper.findAll('.news-tab')
    expect(tabs.map(t => t.text())).toEqual(['头条', '宏观', '国际', '个股', '研报'])
  })

  it('switches to macro tab and loads macro endpoint (F29)', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE })
    apiMock.macro.mockResolvedValue({ data: [{ id: 'm1', title: '央行降准', level: 4, time: '11:00' }] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    await wrapper.findAll('.news-tab')[1].trigger('click')
    await flushPromises()

    expect(apiMock.macro).toHaveBeenCalled()
    expect(wrapper.findAll('.news-item').length).toBe(1)
    expect(wrapper.text()).toContain('央行降准')
  })

  it('switches to research tab with symbol input (F29)', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    apiMock.research.mockResolvedValue({ data: [{ id: 'r1', title: '研报：维持买入', level: 3, time: '09:00' }] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    await wrapper.findAll('.news-tab')[4].trigger('click')
    await flushPromises()

    expect(apiMock.research).toHaveBeenCalledWith('600519')
    expect(wrapper.text()).toContain('研报：维持买入')
  })

  it('WS push ignored outside headlines tab (F29)', async () => {
    apiMock.headlines.mockResolvedValue({ data: [] })
    apiMock.macro.mockResolvedValue({ data: [{ id: 'm1', title: '宏观新闻', level: 4, time: '11:00' }] })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    // 切到宏观 tab
    await wrapper.findAll('.news-tab')[1].trigger('click')
    await flushPromises()

    // WS 推送不应混入宏观列表
    h.getHandler()({ type: 'news', data: { id: 99, title: '头条突发', level: 5 } })
    await wrapper.vm.$nextTick()

    const items = wrapper.findAll('.news-item')
    expect(items.length).toBe(1)
    expect(items[0].text()).toContain('宏观新闻')
    expect(items[0].text()).not.toContain('头条突发')
  })

  // ── F31 (round23 §2.4 A4): 冷启动 partial 标识 ──
  // R8: banner div 常驻 DOM（absolute + display:none）避免显隐造成布局偏移（CLS），
  // 断言类切换 `--show`（jsdom 不计算 scoped CSS 的 display，不能用 isVisible）。
  it('shows partial banner when X-News-Partial header is true (F31)', async () => {
    apiMock.headlines.mockResolvedValue({
      data: [{ id: 'p1', title: '仅一条', level: 3, time: '11:00' }],
      headers: { 'x-news-partial': 'true' },
    })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    expect(wrapper.find('.news-partial-banner').classes()).toContain('news-partial-banner--show')
    expect(wrapper.text()).toContain('数据刷新中')
  })

  it('no partial banner when header absent (F31)', async () => {
    apiMock.headlines.mockResolvedValue({ data: SAMPLE, headers: {} })
    const wrapper = mount(NewsView, { global: { stubs: { VChart: true } } })
    await flushPromises()

    expect(wrapper.find('.news-partial-banner').classes()).not.toContain('news-partial-banner--show')
  })
})


describe('NewsView (F2-8 §9.9)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('expands analysis inline inside the news card (not bottom panel)', async () => {
    newsApi.newsImpact.mockResolvedValue({ data: RESULT })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    // 行内展开区出现（在 li 内部），且不再有页面底部面板
    expect(wrapper.find('.impact-inline').exists()).toBe(true)
    expect(wrapper.find('.impact-panel').exists()).toBe(false)
    expect(wrapper.text()).toContain('利好 A 股宽基')
    expect(wrapper.text()).toContain('510300')
  })

  it('R45: impact 区带"AI 智能分析"层级标签（与新闻卡视觉区分）', async () => {
    newsApi.newsImpact.mockResolvedValue({ data: RESULT })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.impact-header').exists()).toBe(true)
    expect(wrapper.find('.impact-header').text()).toContain('AI 智能分析')
  })

  it('shows loading text while analyzing, then result', async () => {
    let resolveFn
    newsApi.newsImpact.mockImplementation(() => new Promise((res) => { resolveFn = res }))
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.impact-loading').exists()).toBe(true)
    expect(wrapper.text()).toContain('AI 分析中')
    resolveFn({ data: RESULT })
    await flushPromises()
    expect(wrapper.find('.impact-loading').exists()).toBe(false)
    expect(wrapper.find('.impact-summary').exists()).toBe(true)
  })

  it('switches target: analyzing B closes A inline area', async () => {
    newsApi.newsImpact.mockResolvedValue({ data: RESULT })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('利好 A 股宽基')
    await btns[1].trigger('click')
    await flushPromises()
    // A 卡片内展开区消失（impactTarget 已切换）
    const items = wrapper.findAll('.news-item')
    expect(items[0].find('.impact-inline').exists()).toBe(false)
    expect(items[1].find('.impact-inline').exists()).toBe(true)
  })

  it('toggles close when clicking the expanded item again', async () => {
    newsApi.newsImpact.mockResolvedValue({ data: RESULT })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.impact-inline').exists()).toBe(true)
    // 再次点击已展开条目 → 收起
    await btns[0].trigger('click')
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.impact-inline').exists()).toBe(false)
  })

  it('shows inline error with retry on failure (no global crash)', async () => {
    newsApi.newsImpact.mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ data: RESULT })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.impact-inline-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('AI 分析失败')
    // 重试成功
    const retry = wrapper.find('.impact-retry')
    await retry.trigger('click')
    await flushPromises()
    expect(wrapper.find('.impact-summary').exists()).toBe(true)
    expect(wrapper.find('.impact-inline-error').exists()).toBe(false)
  })

  it('R50: 过滤组合外标的（LLM 幻觉不展示）', async () => {
    // 后端返回含组合外标的（600000 幻觉）+ 组合内标的
    newsApi.newsImpact.mockResolvedValue({
      data: {
        summary: '降准利好',
        impact_scope: '市场整体',
        affected_holdings: [
          { symbol: '510300', name: '沪深300ETF', impact_reason: '直接受益' },
          { symbol: '600000', name: '浦发银行', impact_reason: '幻觉标的' },
        ],
        disclaimer: '仅供参考',
      },
    })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    // 组合内标的渲染，幻觉标的被过滤
    expect(wrapper.text()).toContain('510300')
    expect(wrapper.text()).toContain('直接受益')
    expect(wrapper.text()).not.toContain('600000')
    expect(wrapper.text()).not.toContain('浦发银行')
  })

  it('R50: 请求后组合变化不误过滤——按请求时刻快照', async () => {
    newsApi.newsImpact.mockResolvedValue({ data: RESULT })
    const wrapper = await mounted()
    const btns = wrapper.findAll('.news-ai-btn')
    await btns[0].trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('510300')
    // 模拟请求后组合移除 510300（store 变化）——快照仍保留 → 不误过滤
    const { usePortfolioStore } = await import('../stores/portfolio')
    usePortfolioStore().etfs = [{ symbol: '518880', name: '黄金ETF' }]
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('510300')
  })
})

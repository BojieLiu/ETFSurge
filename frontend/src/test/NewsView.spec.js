import { mount, flushPromises } from '@vue/test-utils'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import NewsView from '../components/NewsView.vue'

vi.mock('../api', () => ({
  newsApi: {
    headlines: vi.fn(),
    newsImpact: vi.fn(),
  },
}))

vi.mock('../composables/useNewsWS', () => ({
  useNewsWS: () => ({
    connected: { value: false },
    onNews: vi.fn(),
    connect: vi.fn(),
  }),
}))

vi.mock('../stores/toast', () => ({
  useToastStore: () => ({ show: vi.fn() }),
}))

vi.mock('../stores/portfolio', () => ({
  usePortfolioStore: () => ({
    etfs: [
      { symbol: '510300', name: '沪深300ETF' },
      { symbol: '518880', name: '黄金ETF' },
    ],
  }),
}))

import { newsApi } from '../api'

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
})

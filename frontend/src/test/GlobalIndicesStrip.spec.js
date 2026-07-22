import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import GlobalIndicesStrip from '../components/GlobalIndicesStrip.vue'

describe('GlobalIndicesStrip', () => {
  const mockData = {
    'A股': [
      { symbol: '000001', name: '上证指数', price: 3245.67, change_pct: 1.23,
        available: true, region: 'A股', asset_type: 'index', change_amount: 39.5 },
    ],
    '港股': [
      { symbol: '^HSI', name: '恒生指数', price: 22000.0, change_pct: -0.5,
        available: true, region: '港股', asset_type: 'index', change_amount: -110.0 },
    ],
  }

  it('renders index data when available=true', () => {
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: mockData },
    })
    // Should show price and change, not '暂无'
    expect(wrapper.text()).toContain('3245.67')
    expect(wrapper.text()).toContain('+1.23%')
    expect(wrapper.text()).toContain('22000.00')
    expect(wrapper.text()).toContain('-0.50%')
    expect(wrapper.text()).not.toContain('暂无数据')
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('恒生指数')
  })

  it('shows stale data when available=false but price present', () => {
    const staleData = {
      '港股': [
        { symbol: '^HSI', name: '恒生指数', price: 22000.0, change_pct: -0.5,
          available: false, region: '港股', asset_type: 'index' },
      ],
    }
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: staleData },
    })
    // Should still show the cached price but indicate '已收盘'
    expect(wrapper.text()).toContain('22000.00')
    expect(wrapper.text()).toContain('已收盘')
    expect(wrapper.text()).not.toContain('暂无数据')
  })

  it('shows empty state when globalIndices is empty', () => {
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: {} },
    })
    expect(wrapper.text()).toContain('暂无数据')
    expect(wrapper.text()).toContain('点击刷新获取')
  })

  it('shows placeholder when available=false and price=null', () => {
    const emptyData = {
      'A股': [
        { symbol: '000001', name: '上证指数', price: null, change_pct: null,
          available: false, region: 'A股', asset_type: 'index' },
      ],
    }
    const wrapper = mount(GlobalIndicesStrip, {
      props: { globalIndices: emptyData },
    })
    expect(wrapper.text()).toContain('上证指数')
    expect(wrapper.text()).toContain('—')  // placeholder for both price and change
  })
})

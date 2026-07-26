import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AppTable from '../components/ui/AppTable.vue'
import AppSelect from '../components/ui/AppSelect.vue'
import Skeleton from '../components/ui/Skeleton.vue'

// ── AppTable ───────────────────────────────────────────────
describe('AppTable.vue', () => {
  const sampleColumns = [
    { key: 'name', label: '名称' },
    { key: 'value', label: '值', align: 'right' },
    { key: 'change', label: '变化', sortable: true },
  ]
  const sampleData = [
    { name: 'A', value: 100, change: 0.05 },
    { name: 'B', value: 200, change: -0.03 },
  ]

  it('renders columns as table headers', () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: sampleData },
    })
    const headers = wrapper.findAll('.table__th')
    expect(headers).toHaveLength(3)
    expect(headers[0].text()).toContain('名称')
    expect(headers[1].text()).toContain('值')
  })

  it('renders data rows', () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: sampleData },
    })
    const rows = wrapper.findAll('.table__tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('A')
    expect(rows[1].text()).toContain('B')
  })

  it('renders empty state when no data', () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: [] },
    })
    expect(wrapper.find('.table__empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('暂无数据')
  })

  it('applies align class to th', () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: sampleData },
    })
    const headers = wrapper.findAll('.table__th')
    expect(headers[1].classes()).toContain('table__th--right')
  })

  it('adds sortable class and sorts on click', async () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: sampleData },
    })
    const sortHeader = wrapper.findAll('.table__th')[2]
    expect(sortHeader.classes()).toContain('table__th--sortable')
    await sortHeader.trigger('click')
    expect(wrapper.emitted('sort')).toBeTruthy()
  })

  it('renders with density prop', () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: sampleData, density: 'compact' },
    })
    expect(wrapper.find('.table').classes()).toContain('table--compact')
  })

  it('shows sticky header class when stickyHeader is true', () => {
    const wrapper = mount(AppTable, {
      props: { columns: sampleColumns, data: sampleData, stickyHeader: true },
    })
    expect(wrapper.find('.table-wrapper').classes()).toContain('table-wrapper--sticky-header')
  })
})

// ── AppSelect ──────────────────────────────────────────────
describe('AppSelect.vue', () => {
  const sampleOptions = [
    { value: 'a', label: '选项 A' },
    { value: 'b', label: '选项 B' },
    { value: 'c', label: '选项 C', disabled: true },
  ]

  it('renders options from array', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions },
    })
    const options = wrapper.findAll('option')
    expect(options).toHaveLength(3)
    expect(options[0].text()).toContain('选项 A')
  })

  it('displays label when provided', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions, label: '测试选择' },
    })
    expect(wrapper.find('.select-label').text()).toContain('测试选择')
  })

  it('applies disabled state', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions, disabled: true },
    })
    expect(wrapper.find('select').attributes('disabled')).toBeDefined()
  })

  it('shows placeholder option', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions, placeholder: '请选择' },
    })
    const placeholderOpt = wrapper.find('option[value=""]')
    expect(placeholderOpt.exists()).toBe(true)
    expect(placeholderOpt.text()).toContain('请选择')
  })

  it('shows help text when provided', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions, helpText: '辅助说明' },
    })
    expect(wrapper.text()).toContain('辅助说明')
  })

  it('shows error state', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions, error: '必填项' },
    })
    expect(wrapper.text()).toContain('必填项')
    expect(wrapper.find('select').attributes('aria-invalid')).toBe('true')
  })

  it('disables the disabled option', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions },
    })
    const disabledOpt = wrapper.findAll('option')[2]
    expect(disabledOpt.attributes('disabled')).toBeDefined()
  })

  it('emits update:modelValue on change', async () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions },
    })
    const select = wrapper.find('select')
    await select.setValue('b')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')[0]).toEqual(['b'])
  })

  it('renders with size variant', () => {
    const wrapper = mount(AppSelect, {
      props: { modelValue: '', options: sampleOptions, size: 'sm' },
    })
    expect(wrapper.find('.select-wrapper').classes()).toContain('select-wrapper--sm')
  })
})

// ── Skeleton ───────────────────────────────────────────────
describe('Skeleton.vue', () => {
  it('renders text skeleton by default', () => {
    const wrapper = mount(Skeleton)
    expect(wrapper.find('.skeleton--text').exists()).toBe(true)
    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.attributes('aria-busy')).toBe('true')
  })

  it('renders card skeleton type', () => {
    const wrapper = mount(Skeleton, { props: { type: 'card' } })
    expect(wrapper.find('.skeleton--card').exists()).toBe(true)
  })

  it('renders chart skeleton type', () => {
    const wrapper = mount(Skeleton, { props: { type: 'chart' } })
    expect(wrapper.find('.skeleton--chart').exists()).toBe(true)
  })

  it('renders table skeleton with specified row count', () => {
    const wrapper = mount(Skeleton, { props: { type: 'table', rows: 3 } })
    expect(wrapper.find('.skeleton--table').exists()).toBe(true)
    // 1 header row + 3 data rows
    const rows = wrapper.findAll('.skeleton-table-row')
    expect(rows).toHaveLength(3)
  })

  it('renders avatar skeleton', () => {
    const wrapper = mount(Skeleton, { props: { type: 'avatar' } })
    expect(wrapper.find('.skeleton--avatar').exists()).toBe(true)
  })

  it('renders button skeleton', () => {
    const wrapper = mount(Skeleton, { props: { type: 'button' } })
    expect(wrapper.find('.skeleton--button').exists()).toBe(true)
  })

  it('adds animated class by default', () => {
    const wrapper = mount(Skeleton)
    expect(wrapper.classes()).toContain('skeleton--animated')
  })

  it('removes animated class when animated is false', () => {
    const wrapper = mount(Skeleton, { props: { animated: false } })
    expect(wrapper.classes()).not.toContain('skeleton--animated')
  })

  it('applies custom width to text skeleton', () => {
    const wrapper = mount(Skeleton, { props: { width: '50%' } })
    const lines = wrapper.findAll('.skeleton-line')
    expect(lines[0].attributes('style')).toContain('50%')
  })
})

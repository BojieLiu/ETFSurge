import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AppButton from '../components/ui/AppButton.vue'
import AppCard from '../components/ui/AppCard.vue'
import AppTabs from '../components/ui/AppTabs.vue'
import AppInput from '../components/ui/AppInput.vue'
import AppModal from '../components/ui/AppModal.vue'

// ── AppButton ───────────────────────────────────────────────
describe('AppButton.vue', () => {
  it('renders default slot content', () => {
    const wrapper = mount(AppButton, { slots: { default: 'Click me' } })
    expect(wrapper.text()).toContain('Click me')
  })

  it('applies default props (primary, md)', () => {
    const wrapper = mount(AppButton, { slots: { default: 'OK' } })
    expect(wrapper.classes()).toContain('btn--primary')
    expect(wrapper.classes()).toContain('btn--md')
  })

  it('applies variant prop', () => {
    const wrapper = mount(AppButton, { props: { variant: 'danger' }, slots: { default: 'Del' } })
    expect(wrapper.classes()).toContain('btn--danger')
  })

  it('applies size prop', () => {
    const wrapper = mount(AppButton, { props: { size: 'lg' }, slots: { default: 'Big' } })
    expect(wrapper.classes()).toContain('btn--lg')
  })

  it('disables button when disabled prop is true', () => {
    const wrapper = mount(AppButton, { props: { disabled: true }, slots: { default: 'No' } })
    expect(wrapper.attributes('disabled')).toBeDefined()
    expect(wrapper.classes()).toContain('btn--disabled')
  })

  it('shows loading spinner and disables click', async () => {
    const wrapper = mount(AppButton, { props: { loading: true }, slots: { default: 'Load' } })
    expect(wrapper.find('.btn__loader').exists()).toBe(true)
    expect(wrapper.attributes('disabled')).toBeDefined()
    expect(wrapper.attributes('aria-busy')).toBe('true')
  })

  it('renders icon when provided', () => {
    const wrapper = mount(AppButton, { props: { icon: '⭐' }, slots: { default: 'Star' } })
    expect(wrapper.find('.btn__icon').text()).toBe('⭐')
  })

  it('emits click event when clicked', async () => {
    const wrapper = mount(AppButton, { slots: { default: 'Go' } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
  })

  it('does not emit click when disabled', async () => {
    const wrapper = mount(AppButton, { props: { disabled: true }, slots: { default: 'No' } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeFalsy()
  })

  it('does not emit click when loading', async () => {
    const wrapper = mount(AppButton, { props: { loading: true }, slots: { default: 'Busy' } })
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeFalsy()
  })
})

// ── AppCard ────────────────────────────────────────────────
describe('AppCard.vue', () => {
  it('renders default slot', () => {
    const wrapper = mount(AppCard, { slots: { default: 'Card content' } })
    expect(wrapper.text()).toContain('Card content')
  })

  it('renders title and description', () => {
    const wrapper = mount(AppCard, { props: { title: 'My Title', description: 'My Desc' } })
    expect(wrapper.text()).toContain('My Title')
    expect(wrapper.text()).toContain('My Desc')
  })

  it('applies variant classes', () => {
    const wrapper = mount(AppCard, { props: { variant: 'elevated' } })
    expect(wrapper.classes()).toContain('app-card--elevated')
  })

  it('applies hoverable class', () => {
    const wrapper = mount(AppCard, { props: { hoverable: true } })
    expect(wrapper.classes()).toContain('app-card--hoverable')
  })

  it('applies clickable class and emits click', async () => {
    const wrapper = mount(AppCard, { props: { clickable: true } })
    expect(wrapper.classes()).toContain('app-card--clickable')
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
  })

  it('does not emit click when disabled and clickable', async () => {
    const wrapper = mount(AppCard, { props: { clickable: true, disabled: true } })
    expect(wrapper.classes()).toContain('app-card--disabled')
    await wrapper.trigger('click')
    expect(wrapper.emitted('click')).toBeFalsy()
  })

  it('applies bordered class by default', () => {
    const wrapper = mount(AppCard)
    expect(wrapper.classes()).toContain('app-card--bordered')
  })

  it('renders header slot', () => {
    const wrapper = mount(AppCard, {
      props: { title: 'Test Title', description: 'Sub' },
      slots: { 'header-title': '<span>Header Title Content</span>' },
    })
    expect(wrapper.find('.app-card__header').exists()).toBe(true)
    expect(wrapper.find('.app-card__header').text()).toContain('Header Title Content')
  })

  it('renders footer slot', () => {
    const wrapper = mount(AppCard, { slots: { footer: 'Footer Content' } })
    expect(wrapper.find('.app-card__footer').exists()).toBe(true)
  })

  it('horizontal layout renders icon and content side by side', () => {
    const wrapper = mount(AppCard, {
      props: { layout: 'horizontal', icon: '💰' },
      slots: { default: '<span>Content</span>' }
    })
    expect(wrapper.classes()).toContain('app-card--horizontal')
    expect(wrapper.find('.app-card__main-icon').exists()).toBe(true)
    // Icon renders as SVG via resolvedIcon computed
    expect(wrapper.find('.app-card__main-icon svg').exists()).toBe(true)
    expect(wrapper.text()).toContain('Content')
  })

  it('horizontal layout does not render header or footer', () => {
    const wrapper = mount(AppCard, {
      props: { layout: 'horizontal', icon: '💰', title: 'Test' },
    })
    expect(wrapper.find('.app-card__header').exists()).toBe(false)
    expect(wrapper.find('.app-card__footer').exists()).toBe(false)
  })
})

// ── AppTabs ────────────────────────────────────────────────
describe('AppTabs.vue', () => {
  const tabs = [
    { value: 'a', label: 'Tab A' },
    { value: 'b', label: 'Tab B' },
    { value: 'c', label: 'Tab C', disabled: true },
  ]

  it('renders all tab labels', () => {
    const wrapper = mount(AppTabs, { props: { tabs, modelValue: 'a' } })
    expect(wrapper.text()).toContain('Tab A')
    expect(wrapper.text()).toContain('Tab B')
    expect(wrapper.text()).toContain('Tab C')
  })

  it('marks active tab with aria-selected', () => {
    const wrapper = mount(AppTabs, { props: { tabs, modelValue: 'b' } })
    const activeTab = wrapper.find('[aria-selected="true"]')
    expect(activeTab.text()).toContain('Tab B')
  })

  it('marks disabled tab', () => {
    const wrapper = mount(AppTabs, { props: { tabs, modelValue: 'a' } })
    const disabledTab = wrapper.findAll('.tabs__tab')[2]
    expect(disabledTab.classes()).toContain('tabs__tab--disabled')
    expect(disabledTab.attributes('aria-disabled')).toBe('true')
  })

  it('emits update:modelValue on tab click', async () => {
    const wrapper = mount(AppTabs, { props: { tabs, modelValue: 'a' } })
    const tabs_list = wrapper.findAll('.tabs__tab')
    await tabs_list[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')[0]).toEqual(['b'])
  })

  it('does not emit for disabled tab click', async () => {
    const wrapper = mount(AppTabs, { props: { tabs, modelValue: 'a' } })
    await wrapper.findAll('.tabs__tab')[2].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('renders badge on tab', () => {
    const tabsWithBadge = [
      { value: 'a', label: 'A', badge: 5 },
      { value: 'b', label: 'B' },
    ]
    const wrapper = mount(AppTabs, { props: { tabs: tabsWithBadge, modelValue: 'a' } })
    expect(wrapper.find('.tabs__tab-badge').text()).toBe('5')
  })
})

// ── AppInput ───────────────────────────────────────────────
describe('AppInput.vue', () => {
  it('renders with placeholder', () => {
    const wrapper = mount(AppInput, { props: { placeholder: 'Enter text' } })
    expect(wrapper.find('input').attributes('placeholder')).toBe('Enter text')
  })

  it('renders label', () => {
    const wrapper = mount(AppInput, { props: { label: 'User Name' } })
    expect(wrapper.text()).toContain('User Name')
  })

  it('displays the modelValue', () => {
    const wrapper = mount(AppInput, { props: { modelValue: 'hello' } })
    expect(wrapper.find('input').element.value).toBe('hello')
  })

  it('emits update:modelValue on input', async () => {
    const wrapper = mount(AppInput, { props: { modelValue: '' } })
    const input = wrapper.find('input')
    await input.setValue('new value')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
  })

  it('disables input when disabled prop is true', () => {
    const wrapper = mount(AppInput, { props: { disabled: true } })
    expect(wrapper.find('input').attributes('disabled')).toBeDefined()
  })

  it('shows error message', () => {
    const wrapper = mount(AppInput, { props: { error: 'Required field' } })
    expect(wrapper.text()).toContain('Required field')
    expect(wrapper.find('.input-meta--error').exists()).toBe(true)
  })

  it('shows help text when no error', () => {
    const wrapper = mount(AppInput, { props: { helpText: 'Enter your name' } })
    expect(wrapper.text()).toContain('Enter your name')
    expect(wrapper.find('.input-help').exists()).toBe(true)
  })

  it('renders prefix and suffix', () => {
    const wrapper = mount(AppInput, { props: { prefix: '$', suffix: '.00' } })
    expect(wrapper.find('.input-prefix').text()).toBe('$')
    expect(wrapper.find('.input-suffix').text()).toBe('.00')
  })

  it('shows clear button for clearable input with value', () => {
    const wrapper = mount(AppInput, { props: { modelValue: 'text', clearable: true } })
    expect(wrapper.find('.input-clear').exists()).toBe(true)
  })

  it('clears value on clear button click', async () => {
    const wrapper = mount(AppInput, { props: { modelValue: 'text', clearable: true } })
    await wrapper.find('.input-clear').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
  })

  it('sets aria-invalid when error exists', () => {
    const wrapper = mount(AppInput, { props: { error: 'Error' } })
    expect(wrapper.find('input').attributes('aria-invalid')).toBe('true')
  })
})

// ── AppModal ───────────────────────────────────────────────
const stubTransition = () => ({ render: () => null })

describe('AppModal.vue', () => {
  it('does not render when modelValue is false', () => {
    const wrapper = mount(AppModal, { props: { modelValue: false } })
    expect(wrapper.find('.modal').exists()).toBe(false)
  })

  it('renders title and close button', () => {
    const wrapper = mount(AppModal, {
      props: { modelValue: true, title: 'Confirm', closable: true },
      attachTo: document.body,
    })
    expect(wrapper.text()).toContain('Confirm')
    expect(wrapper.find('.modal__close').exists()).toBe(true)
  })

  it('emits close on close button click', async () => {
    const wrapper = mount(AppModal, {
      props: { modelValue: true, title: 'Modal', closable: true },
      attachTo: document.body,
    })
    await wrapper.find('.modal__close').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
  })

  it('renders default slot content', () => {
    const wrapper = mount(AppModal, {
      props: { modelValue: true },
      slots: { default: 'Modal body content' },
      attachTo: document.body,
    })
    expect(wrapper.text()).toContain('Modal body content')
  })

  it('applies size class', () => {
    const wrapper = mount(AppModal, { props: { modelValue: true, size: 'lg' }, attachTo: document.body })
    expect(wrapper.find('.modal').classes()).toContain('modal--lg')
  })

  it('renders confirm and cancel buttons', () => {
    const wrapper = mount(AppModal, {
      props: { modelValue: true, showConfirm: true, showCancel: true },
      attachTo: document.body,
    })
    expect(wrapper.text()).toContain('取消')
    expect(wrapper.text()).toContain('确认')
  })

  it('emits confirm on confirm button click', async () => {
    const wrapper = mount(AppModal, {
      props: { modelValue: true, showConfirm: true },
      attachTo: document.body,
    })
    await wrapper.find('.modal__footer .btn').trigger('click')
    expect(wrapper.emitted('confirm')).toBeTruthy()
  })
})
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AppSelect from '../components/ui/AppSelect.vue'
import Skeleton from '../components/ui/Skeleton.vue'

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

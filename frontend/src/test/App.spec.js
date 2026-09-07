/**
 * App.vue smoke test — mounts the root component with stubs
 * and verifies it renders without runtime errors.
 *
 * Guards against:
 *   - Missing imports (e.g. `ref` was omitted from `import { ref } from 'vue'`)
 *   - Duplicate named imports (e.g. `{ AppSelect, AppSelect }`)
 *   - Critical component composition errors
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createWebHistory } from 'vue-router'
import App from '../App.vue'

// A minimal route so router-view has something to render
const routes = [
  {
    path: '/',
    name: 'dashboard',
    component: { template: '<div>Dashboard stub</div>' },
    meta: { title: 'Dashboard', description: 'Test' },
  },
]

describe('App.vue', () => {
  let router

  beforeEach(() => {
    setActivePinia(createPinia())
    router = createRouter({ history: createWebHistory(), routes })
    // jsdom does not provide scrollTo
    window.scrollTo = vi.fn()
  })

  it('mounts without error', async () => {
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })

    expect(wrapper.exists()).toBe(true)
  })

  it('renders router-view content via AppLayout slot', async () => {
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
        },
      },
    })

    // The router-view stub should render the dashboard stub
    expect(wrapper.html()).toContain('Dashboard stub')
  })

  it('calls fetchAndMergeTasks on mount', async () => {
    router.push('/')
    await router.isReady()

    const { useTaskStore } = await import('../stores/task')
    const store = useTaskStore()
    const fetchSpy = vi.spyOn(store, 'fetchAndMergeTasks')

    mount(App, {
      global: {
        plugins: [router],
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
          TaskIndicator: { template: '<div />' },
          MarketMonitor: { template: '<div />' },
        },
      },
    })

    expect(fetchSpy).toHaveBeenCalled()
  })

  // ── Z27: WS task_update 处理（§7.2） ───────────────────────────

  it('creates task with type from WS task_type and updates recordId', async () => {
    router.push('/')
    await router.isReady()

    // 假 WebSocket：捕获实例以便注入 onmessage
    const wsInstances = []
    class FakeWebSocket {
      constructor(url) {
        this.url = url
        this.readyState = 0
        this.onopen = null
        this.onmessage = null
        this.onclose = null
        this.onerror = null
        wsInstances.push(this)
      }
      close() { this.readyState = 3 }
    }
    FakeWebSocket.CONNECTING = 0
    FakeWebSocket.OPEN = 1
    const origWS = window.WebSocket
    window.WebSocket = FakeWebSocket

    try {
      const { useTaskStore } = await import('../stores/task')
      mount(App, {
        global: {
          plugins: [router],
          stubs: {
                Teleport: { template: '<div><slot /></div>' },
            TaskIndicator: { template: '<div />' },
            MarketMonitor: { template: '<div />' },
          },
        },
      })

      const ws = wsInstances[0]
      expect(ws).toBeTruthy()

      // check 任务完成消息：task_type='check' + record_id=97
      ws.onmessage({
        data: JSON.stringify({
          type: 'task_update',
          task_id: 9,
          task_type: 'check',
          status: 'completed',
          progress: 100,
          record_id: 97,
        }),
      })

      const store = useTaskStore()
      // WS addTask 保留原始 task_id（数字）；getTask 需传同一类型
      const t = store.getTask(9)
      expect(t).not.toBeNull()
      expect(t.type).toBe('check')
      expect(t.label).toBe('策略检查与分析')
      expect(t.status).toBe('completed')
      expect(t.recordId).toBe(97)
    } finally {
      window.WebSocket = origWS
    }
  })

  it('creates design task with default label when task_type missing', async () => {
    router.push('/')
    await router.isReady()

    const wsInstances = []
    class FakeWebSocket {
      constructor(url) {
        this.url = url
        this.readyState = 0
        this.onopen = null
        this.onmessage = null
        this.onclose = null
        this.onerror = null
        wsInstances.push(this)
      }
      close() { this.readyState = 3 }
    }
    FakeWebSocket.CONNECTING = 0
    FakeWebSocket.OPEN = 1
    const origWS = window.WebSocket
    window.WebSocket = FakeWebSocket

    try {
      const { useTaskStore } = await import('../stores/task')
      mount(App, {
        global: {
          plugins: [router],
          stubs: {
                Teleport: { template: '<div><slot /></div>' },
            TaskIndicator: { template: '<div />' },
            MarketMonitor: { template: '<div />' },
          },
        },
      })

      const ws = wsInstances[0]
      ws.onmessage({
        data: JSON.stringify({
          type: 'task_update',
          task_id: 11,
          status: 'running',
          progress: 10,
          design_id: 222,
        }),
      })

      const store = useTaskStore()
      const t = store.getTask(11)
      expect(t).not.toBeNull()
      expect(t.type).toBe('design')
      expect(t.label).toBe('智能组合设计')
      expect(t.designId).toBe(222)
      expect(t.recordId).toBe(222)
    } finally {
      window.WebSocket = origWS
    }
  })

  // ── F21 (round6 §16.9): 页头标题区域布局优化 ─────────────────────
  it('F21: 页头含品牌图标 + 标题 + 描述（层级分离结构）', async () => {
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
          TaskIndicator: { template: '<div />' },
          MarketMonitor: { template: '<div />' },
        },
      },
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.page-header').exists()).toBe(true)
    expect(wrapper.find('.page-header-icon').exists()).toBe(true)
    expect(wrapper.find('.page-title').text()).toContain('Dashboard')
    expect(wrapper.find('.page-description').exists()).toBe(true)
  })

  // ── R54 (round54-frontend-polish): 移动端汉堡菜单 ─────────────────
  // 负向断言：桌面态（isMobileNav=false）汉堡按钮不渲染、drawer 不存在
  it('R54: 桌面态不渲染汉堡按钮（默认 jsdom 视口 1024px）', async () => {
    router.push('/')
    await router.isReady()

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
          TaskIndicator: { template: '<div />' },
        },
      },
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.nav-burger').exists()).toBe(false)
    expect(wrapper.find('.nav-drawer').exists()).toBe(false)
  })

  // 正向断言：模拟窄视口 → 汉堡出现 → 点击展开 drawer → a11y 属性齐备 → Esc 关闭
  it('R54: 移动态汉堡展开 drawer（a11y 属性 + Esc 关闭）', async () => {
    router.push('/')
    await router.isReady()

    // jsdom 视口默认 1024px，先缩到 767px 触发 isMobileNav
    Object.defineProperty(window, 'innerWidth', { value: 767, configurable: true })
    window.dispatchEvent(new Event('resize'))
    await new Promise((r) => setTimeout(r, 0))

    const wrapper = mount(App, {
      global: {
        plugins: [router],
        stubs: {
          Teleport: { template: '<div><slot /></div>' },
          TaskIndicator: { template: '<div />' },
        },
      },
    })
    // onMounted 内 checkMobileNav 读取 767px
    await wrapper.vm.$nextTick()

    const burger = wrapper.find('.nav-burger')
    expect(burger.exists()).toBe(true)
    expect(burger.attributes('aria-haspopup')).toBe('menu')
    expect(burger.attributes('aria-controls')).toBe('nav-menu')
    expect(burger.attributes('aria-expanded')).toBe('false')

    await burger.trigger('click')
    await wrapper.vm.$nextTick()

    const drawer = wrapper.find('.nav-drawer')
    expect(drawer.exists()).toBe(true)
    expect(drawer.attributes('role')).toBe('menu')
    expect(drawer.attributes('aria-label')).toBe('移动端导航')
    expect(wrapper.findAll('.nav-drawer-link').length).toBe(9)
    expect(burger.attributes('aria-expanded')).toBe('true')

    // Esc 关闭
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.nav-drawer').exists()).toBe(false)

    // 恢复视口
    Object.defineProperty(window, 'innerWidth', { value: 1024, configurable: true })
    window.dispatchEvent(new Event('resize'))
  })
})

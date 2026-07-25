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
          AppLayout: { template: '<div><slot /><slot name="page-header-actions" /></div>' },
          AppToast: { template: '<div />' },
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
          AppLayout: { template: '<div><slot /><slot name="page-header-actions" /></div>' },
          AppToast: { template: '<div />' },
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
          AppLayout: { template: '<div><slot /></div>' },
          AppToast: { template: '<div />' },
          Teleport: { template: '<div><slot /></div>' },
          TaskIndicator: { template: '<div />' },
          MarketMonitor: { template: '<div />' },
        },
      },
    })

    expect(fetchSpy).toHaveBeenCalled()
  })
})

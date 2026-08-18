/**
 * DesignLoading 进度反馈测试矩阵（§7.2 归位合并，2026-08-18）。
 *
 * - LLM-1：progress 卡 80%（LLM 报告生成中）超 60s →「LLM 排队中」；超 150s →
 *   「已接近超时，将降级为方案表格」
 * - F20：任务 stage 对齐设计步骤、已选标的展示、超时预估文案
 */
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignLoading from '../components/design/DesignLoading.vue'

function mountLoading(overrides = {}) {
  return mount(DesignLoading, {
    props: {
      progress: 80,
      stepLabel: 'LLM 报告生成中',
      taskStage: 'LLM 报告生成中',
      elapsedSec: 0,
      ...overrides,
    },
    global: { stubs: { AppButton: { template: '<button><slot /></button>' } } },
  })
}

function mountLoadingF20(props = {}) {
  return mount(DesignLoading, {
    props: {
      progress: 10,
      stepLabel: '正在采集数据...',
      taskStage: '',
      selectedLabel: '',
      ...props,
    },
  })
}

describe('DesignLoading LLM-1 排队提示分级', () => {
  it('LLM 阶段超 60s 显示排队提示（负向：无提示 → FAIL）', () => {
    const wrapper = mountLoading({ elapsedSec: 75 })
    expect(wrapper.text()).toContain('LLM 排队中')
    expect(wrapper.text()).toContain('90s+')
  })

  it('LLM 阶段超 150s 显示接近超时降级提示', () => {
    const wrapper = mountLoading({ elapsedSec: 160 })
    expect(wrapper.text()).toContain('已接近超时')
    expect(wrapper.text()).toContain('降级为方案表格')
  })

  it('LLM 阶段但 elapsedSec ≤ 60 无排队提示（不误报）', () => {
    const wrapper = mountLoading({ elapsedSec: 30 })
    expect(wrapper.text()).not.toContain('LLM 排队中')
    expect(wrapper.text()).not.toContain('已接近超时')
  })

  it('非 LLM 阶段（progress<80）超 60s 走通用等待提示而非排队提示', () => {
    const wrapper = mountLoading({ progress: 40, taskStage: '策略计算完成', elapsedSec: 75 })
    expect(wrapper.text()).toContain('已等待 1 分钟')
    expect(wrapper.text()).not.toContain('LLM 排队中')
  })

  it('仅 progress≥80（无 stage）也判定为 LLM 阶段', () => {
    const wrapper = mountLoading({ taskStage: '', elapsedSec: 90 })
    expect(wrapper.text()).toContain('LLM 排队中')
  })
})

describe('DesignLoading F20 (阶段进度)', () => {
  it('F20: taskStage=LLM 报告生成中 → 高亮"生成组合方案"步骤', async () => {
    const wrapper = mountLoadingF20({ progress: 80, taskStage: 'LLM 报告生成中' })
    await wrapper.vm.$nextTick()
    const steps = wrapper.findAll('.loading-step')
    // 最后一步（生成组合方案）应 active
    expect(steps[steps.length - 1].classes()).toContain('active')
    // 前序步骤应 done
    expect(steps[0].classes()).toContain('done')
  })

  it('F20: taskStage=数据采集与策略计算中 → 第一步 active', async () => {
    const wrapper = mountLoadingF20({ progress: 10, taskStage: '数据采集与策略计算中' })
    await wrapper.vm.$nextTick()
    const steps = wrapper.findAll('.loading-step')
    expect(steps[0].classes()).toContain('active')
  })

  it('F20: 已选标的标签展示（selectedLabel）', async () => {
    const wrapper = mountLoadingF20({ selectedLabel: '沪深300 · 10万' })
    expect(wrapper.text()).toContain('沪深300')
    expect(wrapper.text()).toContain('10万')
  })

  it('F20: 超过 60s 显示超时预估文案', async () => {
    const wrapper = mountLoadingF20({ progress: 60, elapsedSec: 65 })
    expect(wrapper.text()).toContain('预计')
    expect(wrapper.text()).toContain('1-2 分钟')
  })
})

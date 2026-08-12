/**
 * round17 LLM-1: design 任务 LLM 阶段进度反馈分级。
 *
 * - progress 卡 80%（LLM 报告生成中）超 60s → 「LLM 排队中」提示
 * - 超 150s → 「已接近超时，将降级为方案表格」提示
 * - 负向：LLM 阶段但 elapsedSec ≤ 60 无排队提示；非 LLM 阶段超 60s 走通用提示
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

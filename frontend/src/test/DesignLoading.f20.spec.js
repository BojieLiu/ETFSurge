// F20 (round6 §16.8): 等待报告阶段进度——task.stage 对齐 DesignLoading 步骤。
// 规格：加载页展示阶段进度（数据采集→LLM 分析→生成报告，对齐任务 stage 字段）
// + 已选标的/维度高亮 + 取消按钮（已有）+ 超时预估文案。
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DesignLoading from '../components/design/DesignLoading.vue'

function mountLoading(props = {}) {
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

describe('DesignLoading F20 (阶段进度)', () => {
  it('F20: taskStage=LLM 报告生成中 → 高亮"生成组合方案"步骤', async () => {
    const wrapper = mountLoading({ progress: 80, taskStage: 'LLM 报告生成中' })
    await wrapper.vm.$nextTick()
    const steps = wrapper.findAll('.loading-step')
    // 最后一步（生成组合方案）应 active
    expect(steps[steps.length - 1].classes()).toContain('active')
    // 前序步骤应 done
    expect(steps[0].classes()).toContain('done')
  })

  it('F20: taskStage=数据采集与策略计算中 → 第一步 active', async () => {
    const wrapper = mountLoading({ progress: 10, taskStage: '数据采集与策略计算中' })
    await wrapper.vm.$nextTick()
    const steps = wrapper.findAll('.loading-step')
    expect(steps[0].classes()).toContain('active')
  })

  it('F20: 已选标的标签展示（selectedLabel）', async () => {
    const wrapper = mountLoading({ selectedLabel: '沪深300 · 10万' })
    expect(wrapper.text()).toContain('沪深300')
    expect(wrapper.text()).toContain('10万')
  })

  it('F20: 超过 60s 显示超时预估文案', async () => {
    const wrapper = mountLoading({ progress: 60, elapsedSec: 65 })
    expect(wrapper.text()).toContain('预计')
    expect(wrapper.text()).toContain('1-2 分钟')
  })
})

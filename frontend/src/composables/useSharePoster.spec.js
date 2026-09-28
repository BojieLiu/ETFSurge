import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  parseInlineSegments,
  parseBodyBlocks,
  wrapSegments,
  renderPosterCanvas,
} from './useSharePoster'

// Screenshot regression body (MarketReport.vue posterLLM path): raw LLM markdown
// must never reach canvas fillText verbatim.
const SCREENSHOT_BODY = [
  '## 1. 市场全景速览',
  '',
  '- **一句话总结：当前市场处于横盘消化阶段，A股风险偏好走弱**',
  '- 关键数据：上证指数 **3888.3738，-1.22%**；深证成指 **-2.34%**；美股标普500 **+0.51%**',
  '- **成交量变化、涨跌家数比：输入未提供，暂无法验证市场上涨是否获得量能支持。**',
  '- 核心矛盾：**A股成长板块跌幅显著高于上证指数，但美股上涨**',
  '---',
  '## 2. 市场阶段与核心矛盾',
  '- **市场阶段：横盘消化。**依据为市场背景明确标注 **range_bound**',
  '1. 首先看估值分位',
  '2. 再看资金流向',
  '> 引用一句风险提示',
].join('\n')

function mockCtx() {
  return {
    font: '',
    fillStyle: '',
    measureText: (s) => ({ width: String(s).length * 12 }),
    fillText: vi.fn(),
    fillRect: vi.fn(),
  }
}

describe('parseInlineSegments', () => {
  it('splits **bold** runs and strips markers', () => {
    const segs = parseInlineSegments('上证 **-1.22%** 收盘')
    expect(segs).toEqual([
      { t: '上证 ', bold: false },
      { t: '-1.22%', bold: true },
      { t: ' 收盘', bold: false },
    ])
  })

  it('strips links / code to plain text', () => {
    const segs = parseInlineSegments('看[上证](http://x)与`代码`')
    expect(segs.map((s) => s.t).join('')).toBe('看上证与代码')
    expect(segs.some((s) => s.bold)).toBe(false)
  })

  it('unpaired markers do not leak', () => {
    const segs = parseInlineSegments('残留 ** 一半')
    expect(segs.map((s) => s.t).join('')).not.toContain('**')
  })
})

describe('parseBodyBlocks', () => {
  it('classifies headings / bullets / ordered / divider / quote', () => {
    const blocks = parseBodyBlocks(SCREENSHOT_BODY)
    const kinds = blocks.map((b) => b.kind)
    expect(kinds).toContain('heading')
    expect(kinds).toContain('bullet')
    expect(kinds).toContain('divider')
    expect(kinds).toContain('quote')
    const h1 = blocks.find((b) => b.kind === 'heading')
    expect(h1.segments.map((s) => s.t).join('')).toContain('市场全景速览')
    // '- **...' tolerant bullet (no literal '-' left in segments)
    const firstBullet = blocks.find((b) => b.kind === 'bullet')
    expect(firstBullet.marker).toBe('• ')
    expect(firstBullet.segments[0].bold).toBe(true)
    const ordered = blocks.filter((b) => b.kind === 'bullet' && /^\d/.test(b.marker))
    expect(ordered.map((b) => b.marker)).toEqual(['1. ', '2. '])
  })
})

describe('wrapSegments', () => {
  it('no emitted line exceeds maxWidth', () => {
    const ctx = mockCtx()
    const segs = parseInlineSegments('上证指数 **3888.3738，-1.22%**；深证成指连续下跌需要换行处理验证宽度约束')
    const lines = wrapSegments(ctx, segs, 120, '400 22px sans-serif', '600 22px sans-serif')
    expect(lines.length).toBeGreaterThan(1)
    for (const line of lines) {
      const w = line.reduce((a, s) => a + s.t.length * 12, 0)
      expect(w).toBeLessThanOrEqual(120)
    }
  })
})

describe('renderPosterCanvas (markdown-leak regression)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  function withFakeCanvas(ctx) {
    const realCreate = document.createElement.bind(document)
    const fakeCanvas = { width: 0, height: 0, getContext: () => ctx }
    const spy = vi.spyOn(document, 'createElement').mockImplementation((tag) => {
      if (String(tag).toLowerCase() === 'canvas') return fakeCanvas
      return realCreate(tag)
    })
    return { fakeCanvas, spy }
  }

  it('never draws raw markdown tokens; bullets become • glyph', () => {
    const ctx = mockCtx()
    const { spy } = withFakeCanvas(ctx)
    try {
      const canvas = renderPosterCanvas({
        title: '市场研判 · A股',
        modelLine: '模型 · space-bunny-free',
        body: SCREENSHOT_BODY,
        disclaimer: '本工具仅供个人研究，不构成任何投资建议',
      })
      expect(canvas).toBeTruthy()
      const texts = ctx.fillText.mock.calls.map((c) => String(c[0]))
      const joined = texts.join('\n')
      // raw tokens must not leak
      expect(texts.some((t) => t.includes('**'))).toBe(false)
      expect(texts.some((t) => /^#+\s/.test(t))).toBe(false)
      expect(texts.some((t) => /^(---|\*\*\*)$/.test(t.trim()))).toBe(false)
      expect(texts.some((t) => /^- /.test(t))).toBe(false)
      // content preserved, bullet glyph drawn
      expect(joined).toContain('市场全景速览')
      expect(joined).toContain('3888.3738')
      expect(texts.some((t) => t.includes('• '))).toBe(true)
      expect(canvas.height).toBeGreaterThan(420)
      expect(canvas.height).toBeLessThanOrEqual(4000)
    } finally {
      spy.mockRestore()
    }
  })
})

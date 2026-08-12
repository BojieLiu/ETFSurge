/**
 * P0-15 (round16 3.16): 持仓技术分析 K 线红跌绿涨 + 周期标注 + 涨跌幅。
 *
 * 验收：
 * ① candlestick itemStyle color=红(涨)/color0=绿(跌)——源码级断言（参照 round14 P1-K fs.readFileSync 模式）；
 * ② 周期标注 textStyle 非浅灰 #888（字号/对比度足够）；
 * ③ 「今日涨跌」区块存在（分析视图脚本含 changePctInfo 计算 + price-summary-row 模板类）。
 */
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const avSrc = fs.readFileSync(path.resolve(__dirname, '../components/AnalysisView.vue'), 'utf-8')
const taSrc = fs.readFileSync(path.resolve(__dirname, '../components/market/TechnicalAnalysisModal.vue'), 'utf-8')

describe('P0-15 持仓 K 线红涨绿跌（源码级断言）', () => {
  it('AnalysisView candlestick color=红(涨)/color0=绿(跌)（不得写入 color: CANDLE_DOWN 阳线）', () => {
    const m = avSrc.match(/itemStyle: \{ color:([^,]+), color0:([^,]+), borderColor/)
    expect(m).toBeTruthy()
    // color（阳线/涨）必须是 CANDLE_UP（红）
    expect(m[1].trim()).toContain('CANDLE_UP')
    expect(m[2].trim()).toContain('CANDLE_DOWN')
    // 负向：旧实现 color: CANDLE_DOWN, color0: CANDLE_UP 已消除
    expect(avSrc).not.toContain('color: CANDLE_DOWN, color0: CANDLE_UP')
  })

  it('TechnicalAnalysisModal candlestick 同理红涨绿跌', () => {
    expect(taSrc).not.toContain('color: CANDLE_DOWN, color0: CANDLE_UP')
    const m = taSrc.match(/color: CANDLE_UP, color0: CANDLE_DOWN/)
    expect(m).toBeTruthy()
  })

  it('周期标注 fontSize ≥ 14 且非浅灰 #888', () => {
    expect(avSrc).not.toContain("fontSize: 12, fontWeight: 'medium', color: '#888'")
    expect(avSrc).toContain("fontSize: 14, fontWeight: '600', color: '#333'")
  })

  it('今日涨跌区块存在：changePctInfo 计算 + price-summary-row 模板', () => {
    expect(avSrc).toContain('changePctInfo')
    expect(avSrc).toContain('price-summary-row')
    expect(avSrc).toContain('今日涨跌')
  })
})

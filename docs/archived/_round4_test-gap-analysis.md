# 测试防护体系盲区分析（步骤 13/16 结论输入，round4）

> 对照本轮全部发现（R4-01 ~ R4-29，无 R4-04），分析 verify_e2e + 单测防护体系为何未识别。

## 1. 防护体系现状（本轮实测）
- 后端单测：tests/ 大量测试（mock 基线 767，见记忆），单测全过。
- verify_e2e.py：全量 22 个模块组，本轮实测大部分 PASS，但**最终 print_summary 必崩**（R4-18）。
- 前端：Vitest 25 spec + Playwright E2E + LHCI 门禁（.lighthouserc.js P>=60 / CLS<0.1 硬门禁）。
- 但 LHCI 门禁**从未在 CI 中实际跑通**（本轮才首次在容器上手动跑出首页 P57/CLS 0.41，直接 FAIL）。

## 2. 逐发现映射：为什么防护未识别
| 发现 | 防护为何未识别 |
|---|---|
| R4-01 行业集中度误报 | verify_e2e 只验 strategy-check 返回字段存在（summary/holdings_analysis/report_text 非空），**不校验 risk_warnings 内容语义**（「仅覆盖1个行业」是内容级错误）→ PASS |
| R4-02 今日涨跌列空 | verify_e2e R10 检查「今日涨跌列非空」本轮对 design 331 **PASS**（41 单元格），但 design 327 为全部「—」——**检查与数据源状态耦合**（数据源有当日数据才 PASS），数据源降级时静默 PASS |
| R4-03 预期收益未调整 | 无任何检查比较 expected_return vs expected_return_current |
| R4-05 batch 逗号分隔 | verify_e2e 无 realtime/batch 多符号用例；单测只测 datahub 内部（直接传 list），**不测 HTTP Query 解析层** |
| R4-06 news/stock 中文键 | verify_e2e 只测 /news/headlines（英文键），**不测 /news/stock/{symbol}**；前端不消费该端点所以无 UI 断言 |
| R4-07 指数涨幅（已确认为真实行情） | 用户确认韩国指数 +17.91% 为周五真实涨幅——防护无需对 |chg| 设合理性阈值（避免误报）；不列为盲区 |
| R4-09 个股分析基本面缺失 | verify_e2e 只测 symbol-analysis 返回 200/流式长度，**不验报告内容含基本面数据段**；fundamentals 注入缺失在单测（mock 上下文）中不可见；asset_type 非标准值（'stock'）导致 history 失败也无校验 |
| R4-11 前端 4 处弱断裂 | 前端单测用 mock 数据（形状与后端一致），**mock 掩盖了真实响应差异**；Playwright E2E 未覆盖 SectorHeatMap 涨跌幅/Chart KDJ 子图/FactorIC 过滤/FactorModel tooltip |
| R4-13 N04 HK/US 混 A 股 | verify_e2e 不测 llm-report 的 market=HK/US 内容纯净性（只测 200 与结构）；llm-report 单测若 mock indices 则测不出 |
| R4-14 U11 核心层重叠 | verify_e2e 有 diversity 检查（strategy0vs1 diff=4 PASS），**阈值过宽**（diff>=2 即过），未按 U11「重叠<=1」设门禁 |
| R4-15 CDR 验收 FAIL | verify_e2e M7 检查「核心锚(中证A500/沪深300)」**只验沪深300 存在**（core 列表无 A500 也 PASS），验收标准（A500+沪深300 同时出现）未落到门禁 |
| R4-16 U5 组合计算 5.1s | verify_e2e 对 /portfolio/calculate 门禁 5.0s（5.1s 恰好压线过），**门禁=历史问题值时恰好过关**；预热门禁 20s 同理过宽 |
| R4-18 verify_e2e 必崩 | **门禁脚本自身 bug**：print_summary 无 global 声明 → UnboundLocalError。此前多轮「全 PASS」结论实际从未正常打印过总结——**门禁输出的可信度从未被验证** |
| R4-19 首页 CLS 0.41 | LHCI 门禁存在但**未接入 CI/未跑通**；前几轮 Lighthouse 结果来自 /dashboard 或手动选取，首页冷启动路径未被固定测量 |

## 3. 六类系统性根因（归并）
1. **内容语义断言缺失**：e2e 验「字段存在」不验「值合理」（R4-01/R4-03/R4-09/R4-13）。
2. **HTTP 契约层无覆盖**：单测直接调函数（list 参数），e2e 不测 Query 解析形态（R4-05）；SSE 内容不校验（R4-09）。
3. **前端 mock 数据掩盖真实契约**：组件测试 mock 形状与后端一致 → 弱断裂（R4-11）永远测不出。
4. **门禁阈值=历史问题值**：恰好在问题值附近设门（R4-16 5.0s vs 5.1s；R4-14 diversity diff>=2）。
5. **门禁脚本自身可信度未验证**：verify_e2e 必崩仍被当作「跑了」（R4-18）；LHCI 从未在 CI 实际执行（R4-19）。
6. **多市场/多形态未覆盖**：HK/US 报告纯净性（R4-13）、个股资讯端点（R4-06）、个股分析数据完整性（R4-09）。

## 4. 与 round2/round3 结论的关系
- round2 §8、round3 §4.1 已归纳 6 类根因（断言深度不足/降级视为成功/结构耦合退化/请求驱动掩盖/门禁可跳过/单测分层盲区），本轮 R4-01/02/13/16 是其**未收敛的实例**（修复未落地或落地后失效）。
- 本轮**新增**根因：R4-18 门禁脚本自身 bug（防护体系的自检缺失）、R4-19 门禁存在但未接入 CI（空转）。

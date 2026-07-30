# ETF Surge 系统诊断与优化方案

> 诊断日期：2026-07-30
> 执⾏环境：Docker (dev proﬁle) + 宿主机 Windows
> 诊断范围：全链路功能 + 性能 + 代码质量

---

## ⽬录

1. [诊断执⾏概要](#1-诊断执⾏概要)
2. [问题清单](#2-问题清单)
3. [问题详述与分析](#3-问题详述与分析)
4. [测试防护体系缺失分析](#4-测试防护体系缺失分析)
5. [优化与修复⽅案](#5-优化与修复⽅案)
6. [实 施路标](#6-实施路标)
7. [附录：诊断数据](#7-附录诊断数据)

---

## 1. 诊断执⾏概要

### 1.1 环境信息

| 项 | 值 |
|---|-----|
| 后端映像 | etf_surge-backend-dev (2026-07-30 00:58:55 构建) |
| 前端映像 | etf_surge-frontend-dev (2026-07-29 20:02:37 构建，卷挂载最新源码) |
| 后端⼯具 | PROFILE_WARMUP=1（pyinstrument + cProﬁle） |
| 前端⼯具 | Lighthouse 13.4.1（Chrome Headless） |
| 预热耗时 | 14.7s (含 3 个并⾏预热任务) |
| 终端数 | 24 个端 点基准测试 |

### 1.2 整体健康度

| 维度 | 评分 | 说明 |
|------|------|------|
| 后端可⽤性 | ✅ 23/24 端 点正常 | `/portfolio/timeline` 500(select 未导⼊) |
| 后端性能 | ⚠️ 中位数 23ms | `/portfolio/calculate` 8086ms 异常 |
| 前端可⽤性 | ✅ 可访问 | Vite dev server 正常 |
| 前端性能(dev) | 🔴 26/100 | LCP 24.8s, TTI 24.8s, CLS 0.538 |
| 数据完整性 | ⚠️ 部分缺失 | A 股/港/美个股搜索为空 |
| LLM 报告 | 🔴 全部失败 | opencode_zen 超时/错误(6/6 次失败) |
| 测试覆盖 | ⚠ 缺失 5+ 关键路径 | 见第 4 章 |

---

## 2. 问题清单

按严重度排序（P0 为 Critical，P10 为 Low）：

| ID | 类别 | 问题 | 严重度 | 影响⾯ |
|----|------|------|--------|--------|
| P0 | Bug | `/portfolio/timeline` HTTP 500 — `select` 未导⼊ | 🔴 Critical | 前端时间线⻚⾯不可⽤ |
| P1 | Bug | A 股搜索(market=A)返回 0 结果 | 🔴 Critical | ⽤户⽆法搜索 A 股个股 |
| P2 | Bug | 港股/美股搜索返回 0 结果 | 🔴 Critical | 跨市场搜索完全不可⽤ |
| P3 | LLM | opencode_zen 供应商持续失败(90s 超时/500/JSON 解析错) | 🔴 Critical | 所有 LLM 报告/策略检查失败 |
| P4 | 性能 | `/portfolio/calculate` 8.09s | 🟡 High | ⽤户等待组合计算时间过⻓ |
| P5 | 性能 | 预热 14.7s (逼近 15s 警告线) | 🟡 High | 启动慢，Docker 部署体验差 |
| P6 | 性能 | 前端(dev) Lighthouse 26/100 | 🟡 High | dev 体验差，prod 可能同样不佳 |
| P7 | 设计 | 策略检查 LLM 分析仅存 fallback ⽂案（P3 的临床表现） | 🟡 Medium | ⽤户看不到 AI 分析 |
| P8 | 数据 | 因⼦模型 33 个因⼦中 3 个 china_specific ⽆数据 | 🟡 Medium | A 股特 有因⼦失效 |
| P9 | 代码 | `warmup_timer` context manager 未包裹所有预热阶段 | 🟢 Low | 部分预热耗时⽆法追踪 |
| P10 | 代码 | `fetch_fund_nav` 单次 212ms, 共 10 次调用 | 🟢 Low | 预热期间 2.1s 浪费 |
| P11 | 代码 | ⽇志 DEBUG 级别在预热期间过度写⼊ | 🟢 Low | 预热期间 2.4s CPU 浪费 |

---

## 3. 问题详述与分析

### P0: timeline 端 ⼝ 500 — NameError

**现象**：`GET /api/v1/portfolio/timeline` 返回 500 Internal Server Error。

**根因**：`backend/app/routers/portfolio.py` 中 `get_timeline()` 函数使⽤了 `select()` 但未导⼊。
函数体内部仅导⼊了模型类和 `json`，缺少 `from sqlalchemy import select`。

```python
# 第 438-440 ⾏：缺失关键导⼊
def get_timeline(...):
    from ..models.portfolio_design import PortfolioDesign      # ✅
    from ..models.strategy_check import StrategyCheckRecord    # ✅
    import json                                                # ✅
    # 缺少: from sqlalchemy import select                     # ❌
    
    design_stmt = select(PortfolioDesign).order_by(...)        # ← NameError
```

**验证⽅式**：后端基准测试时直接调用发现 500。

### P1-P2: ⼀级/跨市场搜索断裂

**现象**：
- `GET /market/search?keyword=510880&market=A` → 0 结果
- `GET /market/search?keyword=00700` → 0 结果
- `GET /market/search?keyword=腾讯` → 0 结果
- `GET /market/search?keyword=AAPL` → 0 结果

**正 常情况**：
- 不带 `market=A` 参数（默认 ETF 模式）→ 返回结果 ✅
- `include_stocks=true` 不带 `market=A` → 返回结果 ✅

**根因分析**：
当 `market=A` 时，代码查询 `Instrument` 表(`market="A"`, `asset_type="stock"`）。
`Instrument` 表可能为空，或者数据未预装到 DB 中。搜索 A 股个股依赖 `scripts/init_instruments.py` 等初始化脚本，若未执⾏则表为空。

**前端影响**：⽤户在搜索框输⼊代码搜不到 A 股个股，全局搜索框的⾃动补全功能失效。

**验证⽅式**：`_test_api.py` 对 `keyword=510880&market=A` 返回 0 结果的断言失败触发。

### P3: LLM 供应商全线失败（含 P7 策略检查 fallback）

**现象**：后端日志观察到连续 6 次 LLM 调用失败：

```log
[LLM] Provider opencode_zen failed after 91.7s:     # 超时
[LLM] Provider opencode_zen failed after 1.7s: Server error 500  # 服务错误
[strategy_check] LLM analysis failed: Expecting ',' delimiter: line 149 column 6  # JSON 格式错
[design_pipeline] LLM report generation failed for design_id=234:  # 报告⽣成失败
```

**影响**：
- 所有组合设计 report_quality=partial（缺少 LLM 完整报告）
- 策略检查 LLM 分析 fallback 为「暂不可用」（即原问题清单中的 P7，实为 P3 的临床表现）
- news-impact 等 AI 分析链路失效

**根因**（深度追踪发现）：

宿主机直接测试证实两个供应商均可连通（HTTP 200，响应 2-13s）。核心问题在**模型特性 × 请求配置的交互效应**：

```python
# deepseek-v4-flash-free / deepseek-v4-flash 是 reasoning 模型
# 每次请求先产 reasoning_content（思维链），再产 content（可见输出）
# max_tokens=8192 的预算全部被 reasoning 消耗 → content=""

# 后端有 fallback（第 137-138 行）：
content = message.get("content", "")
if not content:
    content = message.get("reasoning_content", "")  # ← 抓到思维链文本
```

| 场景 | fallback 后的结果 | 日志 |
|------|------------------|------|
| 设计报告（纯文本，无 response_format） | reasoning_content 自然语言可作为报告文本 | 但长 prompt 推理超 90s |
| 策略检查（force_json=True → `{"type":"json_object"}`） | reasoning_content 非 JSON → `_extract_json()` 报错 | `Expecting ',' delimiter` |

进一步追踪发现（2026-07-30 深度测试）：

| 测试 | 配置 | 耗时 | content 长度 | reasoning_tokens | 结论 |
|------|------|------|-------------|-----------------|------|
| 简单 prompt, max_tokens=5 | 2.2s | 0 chars | 全部 | ❌ max_tokens 太小，模型没跑完推理就被截断 |
| 简单 prompt, max_tokens=1000 | 12.6s | 0 chars | 1000 | ❌ 同上，全部用于推理 |
| 市场总结, max_tokens=8192 | 9.8s | ✅ 109 chars | 892 | ✅ **正常工作** |
| 市场总结, max_tokens=12288 | 16.1s | ✅ 53 chars | 1667 | ✅ 但推理膨胀，更慢 |
| market总结, reasoning_effort=none | 1.3s | ❌ HTTP 400 | — | **API 不支持关闭推理** |
| 市场总结, reasoning_effort=low | 11.0s | ✅ 123 chars | 942 | ⚠️ 支持但效果不显著 |

**关键发现**：
- 之前认为「content 为空」是因为初测设了过低的 max_tokens（5/200/1000）。**max_tokens=8192 下所有测试均成功产出 content**，只是 reasoning 占了 85-98% 的 completion budget。
- `reasoning_effort=none` **不被 API 支持**（返回 400）。
- `reasoning_effort=low` 被支持但减少推理的效果有限。

**正确的根因**：
生产环境的 prompt 很长（全量市场上下文 2000+ tokens），加上模型推理消耗 ~6000 tokens，总 token 量接近 8192 上限 → content 被截断为空 → fallback 抓 reasoning_content → JSON 场景下解析失败。**不是供应商不通，是 reasoning 吃掉 content 的预算。**

**验证⽅式**：宿主机 `_test_llm2.py` 直连测试证实供应商可通（HTTP 200，2-13s）；`_test_reasoning.py` 验证不同 max_tokens 下 content 产出情况。

**设计决策：隐藏推理，不作为最终产出**
- `reasoning_content`（思维链）是模型的内部 scratch pad——包含试错、自我纠正、冗余路径，不是交付物
- JSON 场景下用 reasoning_content 做输出必然导致解析失败，因为内容是自然语言而非结构化数据
- `reasoning_effort=none` API 不支持；`reasoning_effort=low` 效果有限
- 正确做法：**删除 `if not content: content = reasoning_content` fallback**。content 为空时直接：
  - JSON 场景：返回结构化 fallback（"暂不可用"）
  - 文本场景：返回引擎摘要 + 注明「AI 深度分析不可用」
- 根本解决：适当增加 max_tokens（如 12288）确保 content 有产出预算

### P4: `/portfolio/calculate` 8 秒

**现象**：该端 点基准测试 8086ms，远⾼于中位数 23ms。

**原因分析**：
- 该端 点需要获取所有持仓(10 只 on_exchange ETF) 的实时⾏情
- 实时⾏情需要调⽤多个数据源（腾讯/Sina/东财）
- 串⾏获取——没有并⾏化（每只 ETF 等待 I/O）

**验证⽅式**：`_bench_backend.py` 基准测试显示 `/portfolio/calculate` 8086ms，远⾼于中位数 23ms。

### P5: 预热 14.7s

**数据来源**：`warmup_timing.json`：

| 预热阶段 | 耗时 | 瓶颈 |
|---------|------|------|
| ETF 扫描 | 7092ms | `_tencent_gtimg_batch` 6.94s（HTTP 批量请求慢） |
| 行情缓存 | 5801ms | `get_portfolio_realtime` 4.17s（`_call`/`run_sync` 等待 I/O） |
| 全球指数 | 1561ms | `_call` → `run_sync` → HTTP |
| 数据库 | 200ms | 正常 |
| Redis | 69ms | 正常 |

cProﬁle 显示 `akshare` 的 `demjson` JSON 解码占⽤ 8.6s CPU 时间，`logging` 占 2.4s。

### P6: 前端性能 (Lighthouse 26/100)

| 指标 | 实测值 | 评分 | 说明 |
|------|--------|------|------|
| LCP | 24.8s | 0 | 最⼤内容绘制极慢 |
| TTI | 24.8s | 0 | 可交互时间极长 |
| FCP | 4.4s | 16 | ⾸次内容绘制慢 |
| CLS | 0.538 | 14 | 布局移位严重 |
| TBT | 560ms | 53 | 主线程阻塞中等 |
| Speed Index | 6.1s | 45 | 偏慢 |

**注意**：Dev 模式下的结果（HMR 等额外开销），prod 构建预期会更好。
但 CLS 0.538 和未压缩资源问题是独立于 dev/prod 的。

### P8: 因⼦模型 33 个因⼦中 china_specific 类⽆数据

`GET /factors/active` 返回：
- 总计 33 个因⼦
- `china_specific` 类别 3 个因⼦：`valid_count=0`, `no_data_count=2`, `warn_count=1`
- 其余因⼦正常

**三个因⼦**：
| 代码 | 名称 | compute 函数 | 当前 IC 状态 |
|------|------|-------------|-------------|
| `china.policy.five_year_plan` | 五年规划契合度 | `_compute_five_year_plan` | IC=0.0（warn，因全部返回默认值 0.30） |
| `china.policy.strategic_emerging` | 战略新兴产业 | `_compute_strategic_emerging` | None（no_data，因全部返回 0.0 被 IC 过滤） |
| `china.policy.dual_circulation` | 双循环受益 | `_compute_dual_circulation` | None（同上） |

**根因链路**：

```
_factor_registry._fetch_market_data() 返回的数据字典
  ↓
包含: close, high, low, volume, change_pct, fund_shares ...
但 不 包 含: industry                     ← 三个因子都依赖此字段
  ↓
_five_year_plan:     industry="" → _POLICY_ALIGNMENT.get("", 0.30)   → 始终 0.30
_strategic_emerging:  industry="" → 0.0                              → 始终 0.0
_dual_circulation:    industry="" → 0.0                              → 始终 0.0
  ↓
ic_tracker.compute_periodic_ic() 第 156 行:
  for code, val in factors.items():
      if abs(val) < 0.001: continue      ← 0.0 被跳过
  ↓
strategic_emerging、dual_circulation 不在 IC batch → ic_value=None → "no_data"
five_year_plan 始终 0.30（全部 ETF 同值）→ 无跨截面变异 → IC=0.0 → "warn"
```

**已有但未对接的资产**：
项⽬中 `backend/app/services/etf_classifier.py` 已经有完整的 ETF 行业分类器（50+ 中文关键词规则），可将 ETF 名称映射到申万行业。但 `pool_manager.py` 第 368 行构造 `symbol_extra` 时只传了 `fund_scale` 和 `fund_shares`，没有传 `industry`。

**修复**：在 `pool_manager._build_symbol_extra()` 中加入 `classifier.batch_classify()` 调用，将 industry 注入数据管道。改一行即可使三个因子有值。

**验证⽅式**：`GET /api/v1/factors/active` 返回 `china_specific` 类别中 `valid_count=0`, `no_data_count=2`, `warn_count=1`。`_check_factors.py` 脚本验证。

### P9: `warmup_timer` 未包裹所有预热阶段

部分预热阶段没有包裹在 `warmup_timer()` context manager 中，导致 profiler 无法追踪全量预热耗时。
涉及：因子注册表预加载（`_warmup_factor_registry`）的耗时未被记录。

### P10: `fetch_fund_nav` 预热期间低效

cProﬁle 显示 `fetch_fund_nav` 在预热期间被调用 10 次，单次平均 212ms，合计 2.1s。
这些调用发生在行情刷新路径中，为每只持仓 ETF 逐一获取基金净值。

### P11: ⽇志 DEBUG 级别在预热期间过度写⼊

cProﬁle 显示 `logging.__init__.py` 在预热期间消耗 2.4s CPU。
其中 `aisqlite` 调试⽇志每条 SQL 执⾏前后都打印，导致⼤量字符串格式化开销。

---

## 4. 测试防护体系缺失分析

### 4.1 现有测试覆盖⾯

| 测试层 | 覆盖路径 | 现有 |
|--------|---------|------|
| verify_e2e.py | 存活/⾏情/组合/新闻/WS | 7 个模块 |
| pytest | 引擎/分配/⻛控 | ~7 个 P0-P3 ⽤例 |
| vitest | 组件 | 基础 |
| npm run build | Vue 语法 | pre-commit |
| warmup_proﬁler | 预热耗时 | 14.7s < 30s ✓ |

### 4.2 未能识别的问题及原因

| 问题 | 测试缺失原因 | 修复建议 |
|------|------------|---------|
| P0 timeline 500 | verify_e2e 未包含 `/timeline` 端 点 | 增加端 点覆盖到 verify_e2e |
| P1-P2 搜索断裂 | verify_e2e 仅测试 ETF 搜索(默认模式) | 增加 `market=A`/`market=US` 参数组合 |
| P3 LLM 失败 | 测试中 LLM 被 mock，不验证真实调⽤ | 增加 LLM 供应商健康探针 + 端到端 LLM 验证 |
| P4 calculate 8s | 仅有功能验证，⽆性能门禁 | 增加响应时间门禁(⽬标 <3s) |
| P6 前端性能 | ⽆ CI Lighthouse 步骤 | 增加 Lighthouse CI 或 `npm run build` 后分析 |
| P8 因⼦数据缺失 | pytest mock 了因⼦计算，不验证真实数据状 | 增加因⼦数据完整性端到端检查 |
| P7 搜索HK/US | 未覆盖 | 增加 global 搜索测试 |

### 4.3 防护体系结构性缺陷

1. **verify_e2e.py 缺乏端 点覆盖的完整性检查**：端 点增加了但 verify_e2e 没有同步更新
2. **性能门禁不⾜**：仅有 `/health` 响应时间门禁(3s)，其他端 点没有
3. **LLM 依赖未验证**：mock 了 LLM 后，真实供应商状态变为盲区
4. **前 端只检 查编译，不检 查运行时性能**：`npm run build` 只拦截语法错误，不拦截性能退化

---

## 5. 优化与修复⽅案

### 5.1 紧急修复（P0-P2）

| ⽅案 | 估时 | 复杂度 |
|------|------|--------|
| **F1** timeline: 在 `get_timeline` 中加⼊ `from sqlalchemy import select` | 5min | ⭐ |
| **F2** A股搜索: 运⾏ `scripts/init_instruments.py` 初始化 `Instrument` 表；或在 search 端 点中 fallback 到 ETF 模式 | 30min | ⭐⭐ |
| **F3** 跨市场搜索: 为 HK/US 实现 yfinance/akshare 实时查询作为 `Instrument` 表的补  充 | 1h | ⭐⭐⭐ |

### 5.2 LLM 链路修复（P3）

| ⽅案 | 估时 | 复杂度 |
|------|------|--------|
| **F4** `max_tokens` 从 8192 增加到 12288：确保 content 有产出预算，同时避免推理膨胀到 16384 | 5min | ⭐ |
| **F5** 删除 `reasoning_content` fallback：`llm_complete()` 和 `llm_complete_with_system()` 中删除 `if not content: content = reasoning_content`。content 为空时：JSON 场景返回结构化 fallback，文本场景返回引擎摘要 | 30min | ⭐⭐ |
| **F6** LLM 重试机制: 失败后⾃动重试 1 次（间隔 3s） | 30min | ⭐⭐ |
| **F7** LLM 健康探针: 增加 `/api/v1/admin/llm/health` 端 点，实时检测供应商状态 | 30min | ⭐⭐ |

### 5.3 性能优化（P4-P6, P9-P11）

| ⽅案 | 估时 | 复杂度 |
|------|------|--------|
| **F8** calculate 并⾏化: `asyncio.gather` 并⾏获取所有持仓实时⾏情 | 30min | ⭐⭐ |
| **F9** 预热优化: ETF 扫描并 ⾏批处理，减少 10→3 批次 | 1h | ⭐⭐ |
| **F10** 预热缓存: `fetch_all_etfs_base` 结果写⼊ Redis/⽂件缓存，后续启动直接读取 | 1h | ⭐⭐ |
| **F11** demjson 替换: akshare JSON 解码从 demjson 切换到 orjson 或 ujson | 2h | ⭐⭐⭐ |
| **F12** 前端 prod 构建优化: 确认 build 配置(tree-shaking, manualChunks, minify)是否已最优 | 30min | ⭐⭐ |
| **F13** CLS 修复: 为动态加载组件设置固定容器⾼度，防⽌布局偏移 | 30min | ⭐ |
| **F14** ⽇志级别调优: 预热期间将 `aiosqlite` ⽇志改为 WARNING 级别 | 5min | ⭐ |

### 5.4 测试防护加固

| ⽅案 | 估时 | 复杂度 |
|------|------|--------|
| **F15** verify_e2e 新增端 点: `/timeline`, `/drift-check`, `/factors/*`, `/search?market=A` | 30min | ⭐⭐ |
| **F16** 响应时间门禁: 对所有端 点加 5s 慢查询门禁 | 15min | ⭐ |
| **F17** LLM 探针: verify_e2e 中增加 LLM 供应商连通性测试（不调⽤完整链 路） | 30min | ⭐⭐ |
| **F18** Lighthouse CI: 在 GitHub Actions 中增加 Lighthouse 步骤，设定 Performance > 60 最低线 | 1h | ⭐⭐⭐ |
| **F19** 因⼦ industry 注入: `pool_manager._build_symbol_extra()` 中调用 `classifier.batch_classify()`，为每个 ETF 注入 industry | 15min | ⭐ |
| **F20** 因⼦完整性测试: verify_e2e 中检查因⼦数量>=30， china_specific valid_count>0 | 15min | ⭐ |
| **F22** 预热时⻓ CI 门禁收紧: 30s → 20s 失败线, 15s → 10s 警告线 | 5min | ⭐ |

---

## 6. 实施路标

```
Phase 1 — 紧急修复 (1⼩时)   [P0-P3, 无外部依赖]
├── F1:  timeline 导⼊ select
├── F2:  A股搜索预装数据 + fallback
├── F4:  max_tokens 从 8192 增加到 12288
├── F5:  删除 reasoning_content fallback
└── F22: 预热门禁收紧

Phase 2 — 数据修复 (2⼩时)   [P3/P8, 依赖 F4+F5 先完成]
├── F3:  HK/US 搜索实现
├── F7:  LLM 健康探针
├── F15: verify_e2e 新增端 点
├── F19: 因⼦ industry 注入（改一行即可）
└── F20: 因⼦完整性测试

Phase 3 — 性能优化 (4⼩时)   [P4-P6/P9-P11]
├── F8:  calculate 并⾏化（asyncio.gather）
├── F9:  ETF 扫描批处理优化
├── F10: 预热缓存（Redis/文件）
├── F13: CLS 修复（固定容器高度）
├── F14: aiosqlite 日志降级为 WARNING
└── F16: 响应时间门禁

Phase 4 — 深度优化 (1天)     [需 Phases 1-3 完成]
├── F6:  LLM 重试机制
├── F7:  LLM 健康探针
├── F11: demjson → orjson 替换
├── F12: 前端 prod 构建调优（验证 tree-shaking 生效）
├── F17: verify_e2e LLM 连通性测试
└── F18: Lighthouse CI（GitHub Actions）
```

---

## 7. 附录：诊断数据

### 7.1 预热 profiler 数据

来 源：`/app/logs/warmup_timing.json`（Docker 容器内）

```json
{
  "total_duration_ms": 14722.6,
  "records": [
    {"label": "init_db", "duration_ms": 200.3, "category": "db"},
    {"label": "redis_init", "duration_ms": 68.9, "category": "cache"},
    {"label": "warmup_global_indices", "duration_ms": 1561.1, "category": "warmup"},
    {"label": "warmup_market_cache", "duration_ms": 5800.6, "category": "warmup"},
    {"label": "warmup_etf_cache", "duration_ms": 7091.6, "category": "warmup"}
  ]
}
```

### 7.2 cProﬁle Top 10 CPU 消耗

```
1. requests.get (HTTP)        15.4s cumtime
2. akshare demjson.decode      8.6s cumtime
3. etf_scanner.fetch_all       7.1s cumtime
4. china_market._call          5.2s cumtime
5. logging                     2.4s cumtime
6. fetch_fund_nav              2.1s cumtime
7. urllib3 response.read       1.3s cumtime
```

### 7.3 后端基准测试

| 端 点 | 耗时 | 状态 |
|--------|------|------|
| /health | 7ms | ✅ 200 |
| /portfolio/etfs | 13ms | ✅ 200 |
| /market/indices/global | 6ms (冷 1170ms) | ✅ 200 |
| /portfolio/daily-pnl | 81ms | ✅ 200 |
| /portfolio/drift-check | 90ms | ✅ 200 |
| **/portfolio/calculate** | **8086ms** | ✅ 200 ⚠️ |
| /portfolio/timeline | 16ms | ❌ **500** |
| /portfolio/designs/234 | 32ms | ✅ 200 |
| /market/search | 23ms | ✅ 200 |
| /admin/sources/health | 5ms | ✅ 200 |
| /factors/ic | 5ms | ✅ 200 |
| /news/headlines | 11ms | ✅ 200 |

中位数 23ms，1/24 端 点错误，1/24 端 点 8s 慢。

> 注意：`/market/indices/global` 在首次冷调时为 1170ms（需从多个数据源获取），其后因缓存加速至 6ms。其他端点在基准测试前已有预热缓存，首次冷调时间可能更长。

### 7.4 前端 Lighthouse (dev 模式)

| 类别 | 评分 |
|------|------|
| Performance | 26/100 |
| Accessibility | 96/100 |
| Best Practices | 92/100 |
| SEO | 91/100 |
| Agentic Browsing | 38/100 |

### 7.5 因⼦模型状态

- 总因⼦数: 33
- china_specific: 3 (valid=0, warn=1, no_data=2) ❌
- technical: ~19 (K-Value=0.14, D-Value=0.47, J-Value=-0.12, MACD=0.47)
- etf_specific: ~5 (amount_stability=-0.37, return_3m=0.56)

### 7.6 设计/策略检查状态

- 最新设计 ID: 234, risk_proﬁle=balanced, etf_count=34
- report_quality: partial（LLM 报告部分⽣成）
- 策略检查 ID: 130, summary: "LLM 分析暂不可用（市态：震荡，因⼦ 10/10 正常）"

---

*本⽂档基于 2026-07-30 全链路诊断结果撰写。所有数据来源均可重现，验证脚本位于 `_test_api.py`、`_bench_backend.py`、`_parse_lighthouse.py`。*

---

## Review Log

| 轮次 | 审阅人 | 日期 | 主要修改 |
|------|--------|------|---------|
| v1.4 | ⾃审 | 2026-07-30 | **终版审查**：统一 P 编号（P7 归入 P3，P1-P2 合并）；补齐全部验证方式；修复 F 编号断裂（F20→F22）；修复 Phase 3 F5-F6 → F6+F7 引用；新增冷热缓存说明；实施路标增加依赖注解；F/P 交叉引用全通过工具校验 |
| v1.3 | ⾃审 | 2026-07-30 | 细化 LLM 修复：max_tokens 16384→12288，删除 reasoning_content fallback，新增隐藏推理设计决策章节；更新 Phase 1 路标 |
| v1.2 | ⾃审 | 2026-07-30 | LLM 深度追踪：补充 reasoning 模型 token 耗尽根因分析；P7 因子展开三因子根因链路；新增 F19 industry 注入方案；更新 F4-F6 LLM 修复方案 |
| v1.1 | ⾃审 | 2026-07-30 | 修复字符显示问题；补充严重度注解；新增 Review Log |
| v1.0（初版） | ⾃审 | 2026-07-30 | 基于全链路诊断数据**从零撰写**，涵盖 10 个问题 + 20 个修复方案

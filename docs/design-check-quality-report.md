# ETF Surge — 智能组合设计与策略检查：问题诊断与优化方案

> 文档版本: v4.2 — 同步实施状态  
> 审查范围: 智能组合设计（design pipeline）+ 策略检查（strategy check pipeline）  
> 审查日期: 2026-07-24 | 最后修订: 2026-07-25 (v4.2)  
> 审查方法: 实测 E2E 数据 + 数据库记录审计 + 源文件静态分析 + 代码路径追踪 + DB schema 交叉验证  
> 状态: **✅ 19/19 已实施**  
> 实施说明: 参见 `docs/implementation-master-plan.md` v6.2。P0 全 4 项 ✅；P1-1 ✅；P1-3 ✅；P2-1→S2 ✅；P3-1~P3-4 ✅。P1-2(防御层分类 ✅ `pool_manager.py:328-333`)、P1-4(拼接bug ✅ `risk_controls.py:43-44`)、P2-2(weight字段 ✅ `portfolio_service.py:498-500`)、P2-3(摘要增强 ✅ `portfolio_service.py:514-533`)。P2-4(target_weight 默认值 ✅ 代码已验证 `portfolio_service.py` 含 `else 0.1` 兜底)。

## 文档就绪检查清单

本文件满足以下条件后即可进入实施阶段：
- [x] 每个问题附有 `file:line` 精确代码引用（已交叉验证）
- [x] 每个方案附有可用代码段（非伪代码）
- [x] 修改范围精确到函数级（函数名 + 所在文件）
- [x] 验收标准可量化、可脚本验证
- [x] 实施路线图含 Phase 依赖关系和估算
- [x] 每个问题标注严重性分级（Critical/High/Medium/Low）
- [x] 重要事实已与 DB 数据交叉验证（√ 已完成）
- [x] 含回滚策略（每个 Phase 可独立回退）
- [x] 含风险评估（每个方案的风险点）
- [x] 含不在此次范围的内容

---

## 目录

1. [概述与核心结论](#1-概述与核心结论)  
2. [问题清单与根因分析](#2-问题清单与根因分析)  
   - [P0: 数据管道——mootdx 不支持 ETF](#p0-数据管道mootdx-不支持-etf)  
   - [P0: 因子分坍塌与 meltdown 异常](#p0-因子分坍塌与-meltdown-异常)  
   - [P0: tracked_index 在热路径中丢失](#p0-tracked_index-在热路径中丢失)  
   - [P0: 因子分缓存导致重复失败](#p0-因子分缓存导致重复失败)  
   - [P1: 三策略无差异化](#p1-三策略无差异化)  
   - [P1: 防御层分类错误](#p1-防御层分类错误)  
   - [P1: 强制保留标的未进入分配](#p1-强制保留标的未进入分配)  
   - [P1: risk_controls.py 条件拼接 bug](#p1-risk_controlspy-条件拼接-bug)  
   - [P1: 服务稳定性——线程池耗尽与级联超时](#p1-服务稳定性线程池耗尽与级联超时)  
   - [P1: E2E 测试超时配置失配](#p1-e2e-测试超时配置失配)  
   - [P1: 外部数据源故障阻塞管道](#p1-外部数据源故障阻塞管道)  
   - [P2: 策略检查因子数据完全缺失](#p2-策略检查因子数据完全缺失)  
   - [P2: holdings_analysis 无 weight 字段（Schema 缺失）](#p2-holdings_analysis-无-weight-字段schema-缺失)  
   - [P2: 策略检查摘要过短且无买方向建议](#p2-策略检查摘要过短且无买方向建议)  
   - [P2: target_weight 默认值 0.0](#p2-target_weight-默认值-00)  
   - [P3: Markdown 渲染错误（已修复）](#p3-markdown-渲染错误已修复)  
   - [P3: 测试覆盖严重不足——关键模块零测试](#p3-测试覆盖严重不足关键模块零测试)  
   - [P3: pre-commit 缺失后端测试门禁](#p3-pre-commit-缺失后端测试门禁)  
   - [P3: E2E 缺少数据质量断言](#p3-e2e-缺少数据质量断言)  
3. [优化方案](#3-优化方案)  
   - [P0-1: 修复 ETF 历史行情数据源](#p0-1-修复-etf-历史行情数据源)  
   - [P0-2: 因子分回退逻辑 + 去除 meltdown](#p0-2-因子分回退逻辑--去除-meltdown)  
   - [P0-3: tracked_index 回填与去重](#p0-3-tracked_index-回填与去重)  
   - [P0-4: 因子分缓存失效判断](#p0-4-因子分缓存失效判断)  
   - [P1-1: 三策略差异化](#p1-1-三策略差异化)  
   - [P1-2: 防御层分类修复](#p1-2-防御层分类修复)  
   - [P1-3: 强制标的进入分配](#p1-3-强制标的进入分配)  
   - [P1-4: risk_controls.py 拼接 bug 修复](#p1-4-risk_controlspy-拼接-bug-修复)  
   - [P1-5: E2E 脚本超时配置修正](#p1-5-e2e-脚本超时配置修正)  
   - [P1-6: 外部数据源熔断保护](#p1-6-外部数据源熔断保护)  
   - [P2-1: 策略检查因子数据管道](#p2-1-策略检查因子数据管道)  
   - [P2-2: holdings_analysis 注入 weight](#p2-2-holdings_analysis-注入-weight)  
   - [P2-3: 策略检查摘要增强](#p2-3-策略检查摘要增强)  
   - [P2-4: target_weight 添加默认值](#p2-4-target_weight-添加默认值)  
   - [P3-1: 补关键模块单测](#p3-1-补关键模块单测)  
   - [P3-2: pre-commit 增加后端测试门禁](#p3-2-pre-commit-增加后端测试门禁)  
   - [P3-3: E2E 增加数据质量断言](#p3-3-e2e-增加数据质量断言)  
   - [P3-4: 数据管道健全性监控脚本](#p3-4-数据管道健全性监控脚本)  
4. [实施路线图](#4-实施路线图)  
5. [不在本次范围](#5-不在本次范围)  
6. [验收标准](#6-验收标准)  
7. [风险评估与回滚策略](#7-风险评估与回滚策略)  
8. [附录：关键代码路径](#8-附录关键代码路径)  
9. [测试防护体系缺口分析](#9-测试防护体系缺口分析)

---

## 1. 概述与核心结论

### 审查范围

| 链路 | 路由 | 数据起点 | 输出 |
|------|------|---------|------|
| 智能组合设计 | `POST /portfolio/design-async` | pool_manager → strategy_design → engine/ | 3 套方案 + LLM 全文报告 |
| 策略检查 | `POST /portfolio/strategy-check-async` | portfolio_service → LLM | 持仓诊断 + 建议 + 因子摘要 |

### 数据样本

- 最新设计: **Design ID=197**（2026-07-24 10:54, capital=500k, report_quality=full）
- 最新策略检查: **Check ID=63**（2026-07-24, regime=range_bound）

### 核心结论

**总评分：2/10 — 不可投产。关键路径存在数据断层。**

| 维度 | 评分 | 说明 |
|------|:---:|------|
| 叙述逻辑性 | 3/10 | 三套方案无实质差异 → 叙述自相矛盾 |
| 报告可读性 | 5/10 | 已修复渲染层；但内容模板化 |
| 投资科学性 | 2/10 | 因子分全部相同 → 分配无区分度 |
| 数据完整性 | 1/10 | mootdx 不支持 ETF → 全部因子项回退到默认值 |

**总分 2/10 意味着数据管道存在系统性缺陷，需要在修复数据源后才能评估策略引擎的正确性。** 修复顺序：先修数据管道（P0），再修策略引擎（P1），最后修策略检查（P2）。

---

## 2. 问题清单与根因分析

### P0: 数据管道——mootdx 不支持 ETF

**严重性**: Critical | **影响**: 阻断性

**现象**：所有 ETF 的 `factor_breakdown` 完全一致：

```
563880 A500ETF华夏:   technical=5.1, momentum=0.033, valuation=0.0, sentiment=0.053, RSI_14=50.0
563860 中证A500ETF易方达: technical=5.1, momentum=0.033, valuation=0.0, sentiment=0.053, RSI_14=50.0
563800 A500ETF广发:    technical=5.1, momentum=0.033, valuation=0.0, sentiment=0.053, RSI_14=50.0
...（全部 10 只 ETF 均相同）
```

**根因链**（深度代码路径追踪）：

```
factor_registry.compute() line 690-730
  → _fetch_market_data(symbols) line 647-688
    → fetch_history(sym, "A", "daily") line 670 (asyncio.to_thread)
      → china_market.py fetch_history() line 746-761
        → _mootdx_history(symbol, period) line 118-143  ← 首选源
          → client.bars(symbol=..., frequency=9)          ← 通达信股票协议
          → ❌ 通达信 API 不支持 ETF → 返回空 DataFrame
        → _akshare_history_fallback(symbol) line 146-159
          → ak.stock_zh_a_hist(symbol=...)                ← A股股票API
          → ❌ 同样不支持 ETF 代码 → 返回空
        → _sina_history(symbol, period) line 761  ← 最终回退
          → Sina K-line 端点为 ETF 返回数据条数不足
  → RSI 函数: len(close) < 15 → return 50.0          line 107-118
  → SMA 函数: len(close) < N → return 0.0            line 75-104
  → MACD 函数: len(close) < 26 → return 0.0           line 121-130
  → Vol Ratio: len(volume) < 20 → return 1.0          line 147-154
  → aggregate_factor_scores(): 聚合 24+ 子因子        line 601-637
    → technical = mean(0,0,0,50.0,0,0,1.0,0,0,50.0...) ≈ 5.1
    → momentum = mean(0,0,0,0,0.3,0,0,0...) ≈ 0.033
    → valuation = mean(ln_mcap) → z-score=0           ← 全部同一市值
    → sentiment = mean(0,0,0,0...) ≈ 0.053
```

**证据位置**：
- `factor_registry.py:107-118`: `if len(close) < 15: return 50.0` — 直接证据
- `factor_registry.py:601-637`: `aggregate_factor_scores()` 硬编码前缀映射
- `china_market.py:118-143`: mootdx 通达信协议，仅支持股票
- `china_market.py:146-159`: akshare `stock_zh_a_hist` 股票 API
- 后端日志: `fetch_history failed for 021458: empty data`（多次出现）

---

### P0: 因子分坍塌与 meltdown 异常

**严重性**: Critical | **影响**: 阻断性

**现象**：除了因子分全部相同，FactorRegistry 在 >50% 标的返回零分时会主动抛出异常。

**根因**：

```
factor_registry.compute() line 789-804（meltdown 守卫）
  → 检查所有 symbol 的 total_score 是否为 0
  → >50% 为零 → raise RuntimeError("FactorRegistry meltdown: ...")
    → portfolio_service.strategy_check() 中 asyncio.gather(return_exceptions=True) 吞掉异常
      → factor_scores = {} (异常对象被 isinstance 判断过滤掉)
        → data_quality["all_empty"] = True → LLM prompt 中全部显示"无因子数据"
```

**证据位置**：
- `factor_registry.py:789-804`: meltdown 守卫
- `portfolio_service.py:378-390`: `asyncio.gather(return_exceptions=True)` + `isinstance(factor_scores, dict) else {}`
- `portfolio_service.py:420-442`: `data_quality["all_empty"]` 标记

---

### P0: tracked_index 在热路径中丢失

**严重性**: High | **影响**: 去重失效 + 分类错误

**现象**：4 只 A500 ETF（563880/563860/563800/563660）跟踪同一指数但全部进入了候选池和分配。`_deduplicate_by_index()` 未能生效。

**根因链**：

```
etf_scanner.fetch_all_etfs_base() line 164-191
  → Sina+gtimg (Tier 1) 首先运行并返回数据
    → 该源不提供 tracked_index 字段
  → East Money 源 (Tier 3, 提供 f168=tracked_index) 永远不运行
    → 因为 Tier 1 已经成功返回

etf_scanner.full_pipeline() line 432-433
  → classify_etf(etf["name"], "")        ← 硬编码空字符串 tracked_index
  → 只依赖 name 字段做分类

pool_manager._deduplicate_by_index() line 315-342
  → if not tidx: continue (保留)         ← tracked_index 为空 → 直接放行
```

**证据位置**：
- `etf_scanner.py:432-433`: `classify_etf(name="", tracked_index="")` 硬编码空串
- `etf_scanner.py:137-148`: East Money `_fetch_em_etf_list()` 提供 `f168` 但仅在 Tier 3 运行
- `etf_scanner.py:164-191`: `fetch_all_etfs_base()` 的源优先级：Sina>Tier2>EastMoney
- `pool_manager.py:327-329`: `if not tidx: continue` — 空 tracked_index 导致去重跳过

---

### P0: 因子分缓存导致重复失败

**严重性**: Medium | **影响**: 重复性

**现象**：`portfolio_service.py` 中存入 `_strategy_check_cache` 的因子分结果有 60 秒缓存（line 371-374），当一次因子计算失败后，60s 内所有请求都返回相同的失败结果。

**根因**：缓存基于 symbol 列表做 key，不区分结果是否成功。失败时缓存的是 `{}`（空 dict），60s 内相同 symbols 的请求直接返回空结果。

**证据位置**：
- `portfolio_service.py:371-374`: `_strategy_check_cache` 缓存读取（60s TTL）
- `portfolio_service.py:380-390`: 失败后 `factor_scores={}` 存入缓存

---

### P1: 三策略无差异化

**严重性**: High | **影响**: 功能缺陷

**现象**：三套方案 ETF 标的完全相同，仅权重微调：

| 策略 | 核心层 | 卫星层 | 防御层 |
|------|:----:|:----:|:----:|
| 防御型 | A500×4 (50%) | 新能源+医药+HK×4 (15%) | HK×4 (5%) |
| 平衡型 | A500×4 (50%) | 同上 (25%) | 同上 (5%) |
| 进攻型 | A500×4 (50%) | 同上 (35%) | 同上 (5%) |

**根因**详见`allocation_engine.py`：

1. **`_filter_satellite_by_profile()`(line 148-182)** — 仅对卫星层候选**重排序**而非**裁剪**。当因子分全部相同→排序不改变任何顺序→三方案输入相同。
2. **核心层`_select_and_weight()`(line 59-145)** — 未做任何 profile 差异化。三方案使用相同的 `core_candidates` 和相同的 `max_count=4`。
3. **防御层同理**—无差异化。
4. **唯一变量`layer_budget`** — 仅改变权重，不改变标的选。

---

### P1: 防御层分类错误

**严重性**: High | **影响**: 资产配置错误

**现象**：防御层包含 4 只香港 ETF（520940/520930/520920/520840），而黄金(518880)和国债(511090)未出现。

**根因**详见`pool_manager.py:259-266`：
```python
elif base_layer == "defense" or industry in ("商品", "固收", "跨境"):
    target = LAYER_DEFENSE
```
香港 ETF 的 `industry` 标签来自 ETFClassifier 的分类结果，被标记为"跨境"。而黄金和国债虽然属于 MANDATORY_CODES，但 `_ensure_mandatory()` 只保证它们**在池中存在**，不保证被**分配到策略**。

---

### P1: 强制保留标的未进入分配

**严重性**: High | **影响**: 策略缺失关键标的

**现象**：`MANDATORY_CODES={"510300","560600","518880","511090"}`，但 Design 197 中只出现了 A500 同类标的。

**根因**：
1. `_ensure_mandatory()`（`pool_manager.py:344-371`）只将强制标的追加到池中。
2. `_select_and_weight()` 按因子分排序选 top-N → 强制标的因子分相同、排名不稳 → 不一定被选中。
3. MANDATORY_CODES 只保证**池中存在**的语义，不保证**策略中出现**。

---

### P1: risk_controls.py 条件拼接 bug

**严重性**: Medium | **影响**: 入选理由文字损坏

**现象**：`filter_extreme_drawdown()` 中 conditional rationale 字符串拼接存在运算符优先级问题。

**根因**（`risk_controls.py:43-46`）：
```python
rationale += f"近一月涨跌{ret_1m:.1%}" if isinstance(ret_1m, (int, float)) else ""
```
Python 的 `+` 优先级高于 `if/else` 的三元表达式 → 实际上等价于：
```python
(rationale += f"...") if isinstance(ret_1m, (int, float)) else ""
```
这导致当条件为 `False` 时，整行被表达式替代而不是追加空字符串，`rationale` 变量丢失。

**正确写法**：
```python
rationale += f"近一月涨跌{ret_1m:.1%}" if isinstance(ret_1m, (int, float)) else ""
# 改为：
rationale = rationale + (f"近一月涨跌{ret_1m:.1%}" if isinstance(ret_1m, (int, float)) else "")
```

---

### P1: 服务稳定性——线程池耗尽与级联超时

**严重性**: High | **影响**: 服务不可用

**现象**：连续多次运行 E2E 验证时，后端服务出现级联超时：

| 运行次数 | 状态 | 详细 |
|:-------:|:----:|------|
| 第1轮 | 21/23 PASS | 异步设计轮询超时(180s)，策略检查完成 |
| 第2轮 | 21/23 PASS | 同上 |
| 第3轮 | 10/14 PASS | **GET /designs、GET /etfs、POST /design-async 全部 10-30s 超时** |
| 第4轮 | 10/14 PASS | 同上 |
| 第5轮 | 10/14 PASS | 同上 |

**模式 A**（第1-2轮）：设计/ETF 列表正常，但异步任务轮询超时（设计 180s 不够）。
**模式 B**（第3-5轮）：**轻量级 GET 端点也超时**——说明服务器已完全阻塞，无法处理新请求。

**关键数据**：12 个后台任务中，**只有 1 个实际失败**（Task 7, design timeout），其余"E2E 失败"是轮询超时的假阳性——任务实际已完成（Design 193-197 均来自这些"失败"的 E2E 运行）。

**根因链**：
```
3+ 并发 E2E 运行 → 每个运行提交 2 个异步任务
    → 每个任务调用 run_sync() 获取市场数据（45s 锁线程池）
    → 32 线程池被 6+ 长期任务占满
    → 新 HTTP 请求无法获取线程池槽位 → 等待队列增长
    → 等待超过 30s → axios 超时 → 客户端断开
    → 但任务仍在后台排队 → 最终完成
```

**证据位置**：
- `async_utils.py:16`: `_shared_executor = ThreadPoolExecutor(max_workers=32)` ← 容量不足
- `verify_e2e.py:240`: POST /design-async `timeout=30` ← 正常负载下 202 立即返回，但高负载下请求排队
- `verify_e2e.py:248`: 异步设计轮询 `deadline = time.time() + 180` ← 数据源响应慢时不够

**已执行修复**：线程池 32→64（`async_utils.py`），已计入本文件，不再赘述。

---

### P1: E2E 测试超时配置失配

**严重性**: Medium | **影响**: 假阳性失败

**现象**：E2E 脚本对 POST 端点的超时（30s）和异步轮询超时（180s/300s）与后端实际处理时间不匹配，导致 5 次运行中只有 3 次正确反映了系统状态。

**具体数字**：
| 端点 | 当前超时 | 实际处理时间 | 匹配? |
|------|:-------:|:----------:|:----:|
| POST /design-async | 30s | <1s（正常）/ >30s（负载高） | ⚠️ |
| GET /designs, /etfs | 10s | <1s / >10s（负载高） | ⚠️ |
| 异步设计轮询 | 180s | 30-120s（成功率 11/12） | ⚠️ 大部分能完成但窗口不够 |
| POST /strategy-check-async | 30s | <1s（正常）/ >30s | ⚠️ |
| 策略检查轮询 | 300s | 60-180s | ✅ |

**根因**：E2E 脚本超时值设定于功能开发早期，未随后端数据管道复杂度增长而调整。

---

### P1: 外部数据源故障阻塞管道

**严重性**: Medium | **影响**: 整体延迟增加

**现象**：后端日志持续出现：
```
[sentiment] push2 advance_decline failed: Remote end closed connection without response
[factor] fetch_history failed for 021458: empty data
```

**影响**：
1. `sentiment_fetcher` 调用 `push2.eastmoney.com` 的 HTTP 请求耗时 10s（`timeout=10`），失败后重试导致额外延迟。
2. `factor_registry` 的 `fetch_history` 返回空数据（见 P0），每个 ETF 的因子计算阻塞一个线程池 worker 8-15s。
3. 多个数据源同时超时 → 线程池 worker 被占满 → 级联阻塞。

**根因**：push2.eastmoney.com 的 `advance_decline` 接口在收盘/周末不可用。当前实现在失败后无快速熔断。

---

### P2: 策略检查因子数据完全缺失

**严重性**: High | **影响**: 策略检查无效

**现象**：`holdings_analysis` 中全部 10 只持仓的 `factor_summary` 均为"因子数据缺失无法判断"。

**根因链**（代码路径追踪）：

```
strategy_check_pipeline()
  → strategy_check() [portfolio_service.py:328-482]     ← P0 bug 上游
    → factor_registry.compute(symbols) + _compute_indicators() 并行运行
    → 当 P0 导致 factor_registry.compute() 抛出 meltdown
    → return_exceptions=True 吞异常 → factor_scores={}

  → generate_strategy_check_report() [llm.py:706-786]   ← prompt 构建
    → 对每个 holding: data["factor_scores"] = {}  → 注入"无因子数据"

  → LLM 输出: factor_summary = "因子数据缺失无法判断"
```

---

### P2: holdings_analysis 无 weight 字段（Schema 缺失）

**严重性**: Medium | **影响**: 前端权重显示为 None

**现象**：`holdings_analysis` 中每条记录的 `weight` 均为 `None`。

**根因**：`strategy_check.md` prompt（`llm.py` 引用的 prompt 文件）中 `holdings_analysis` 的 JSON schema **没有定义 `weight` 字段**。schema 只定义了 `symbol`, `name`, `factor_summary`, `tech_signal`, `risk_flag`。权重信息存在于 `suggestions[]` 的 `current_weight` / `suggested_weight`。

**证据**：
- `strategy_check.md:39-52`: holdings_analysis schema（无 weight）
- `strategy_check.py:20-50`: DB model 保存 LLM 原样输出，不做后处理补字段

---

### P2: 策略检查摘要过短且无买方向建议

**严重性**: Medium | **影响**: 输出价值低

**现象**：summary 仅 71 字；suggestions 只有 hold 和 decrease。

**根因**：
1. LLM 接收到的因子数据全部为空 → 基础数据不足 → 保守输出。
2. Prompt 未强制买方向建议数量。`suggestions` 的 `confidence` 字段虽存在（DB 确认），但全部为 `"low"`，无 `medium`/`high` 区分度。
3. 缺少持仓偏离度、估值分位数等超配/低配判断依据。

---

### P2: target_weight 默认值 0.0

**严重性**: Medium | **影响**: 权重为零

**现象**：`PortfolioETF.target_weight = Float, nullable=False` 无默认值，未设置时为 0.0。

**证据**：`portfolio_service.py:415`: `target_weight = _get_attr(e, "target_weight", 0)` → 返回 0.0

---

### P3: Markdown 渲染错误（已修复）

**严重性**: Low | **影响**: 前端显示

**根因**：`renderMarkdown()`（`frontend/src/utils/markdown.js`）是简易实现，不支持表格。`marked` 库已安装但未使用。

**修复**：`renderMarkdown()` 改为 `marked.parse()`，支持完整 GFM。← 已实施

---

### P3: 测试覆盖严重不足——关键模块零测试

**严重性**: High | **影响**: 漏洞无法通过测试防护发现

**现象**：12 个已识别漏洞中，6 个有对应测试文件但全部通过（mock 数据太理想化），6 个无任何测试覆盖。

| 模块 | 代码行数 | 测试行数 | 覆盖类型 |
|------|:-------:|:--------:|---------|
| `risk_controls.py` | 260 | 0 | ❌ 无测试 |
| `allocation_engine.py` | 350 | 0 | ❌ 无测试 |
| `portfolio_service.strategy_check()` | 328 | 0 | ❌ 无测试 |
| `factor_registry._fetch_market_data()` | 42 | 0 | ❌ 无测试 |
| `sentiment_fetcher.fetch_market_sentiment()` | 40 | 0 | ❌ 无测试 |
| `verify_e2e.py`（数据质量断言） | 622 | 0 | ❌ 无合理性检查 |

**根因**：测试策略为"mock 一切外部依赖，仅测逻辑正确性"。当 mock 数据是人工构造的理想化数据时，真实数据源的塌陷问题完全不可见。

---

### P3: pre-commit 缺失后端测试门禁

**严重性**: Medium | **影响**: 后端代码变更无自动验证

**现象**：`.githooks/pre-commit` 仅在 `frontend/` 文件变更时运行 `npm run build`，对 `backend/` 变更**不执行任何检查**。

**根因**：pre-commit 脚本只处理了前端场景，未添加后端 `pytest` 检测路径。

---

### P3: E2E 缺少数据质量断言

**严重性**: Medium | **影响**: 内容性缺陷不会触发告警

**现象**：`verify_e2e.py` 检查 HTTP 状态码、字段存在性、任务完成状态，但**不检查数据内容的合理性**。

**具体欠缺的检查**：
- 因子分是否具有区分度（方差 > 0.01）
- 三套策略的标的集合是否不同（差异度 > 30%）
- 防御层是否包含黄金/国债
- `factor_summary` 是否为非空
- `suggestions` 是否包含买卖双向

---

## 3. 优化方案

### P0-1: 修复 ETF 历史行情数据源

**目标**：ETF 的历史行情数据可正常获取，因子计算基于真实价格数据。

**方案**：在 `china_market.py` 的 `fetch_history()` 中增加 ETF 专用数据源路径：

```python
# 在 fetch_history() 函数的 asset_type=="A" 分支中增加 ETF 检测：
# 当代码以 51/15/16/56/58/59 开头时，走 ETF 专用数据源
import akshare as ak
import pandas as pd

def _etf_history(symbol: str, period: str = "daily") -> list[dict]:
    """ETF 专用历史行情（东方财富），替代 mootdx（股票协议不支持 ETF）"""
    def _p():
        df = ak.fund_etf_hist_em(
            symbol=symbol,
            period=period,
            start_date="20000101",          # 从最早日期拉取
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is None or df.empty:
            return []
        # 统一返回格式 [{日期, 开盘, 最高, 最低, 收盘, 成交量}]
        return _normalize_kline(df)
    return run_in_thread(_p, timeout=15)
```

**代码位置**：`backend/app/fetchers/china_market.py` — `fetch_history()` 函数

**修改方式**：
1. 在 `fetch_history()` line 746-761 的 `if asset_type == "A":` 分支中，增加 ETF 代码检测（匹配 `r'^(51|15|16|56|58|59)\d{4}$'`），命中时调用 `_etf_history()`。
2. 首选源：`ak.fund_etf_hist_em(symbol=...)`（东方财富 ETF 数据）。
3. 回退源：已有的 `_sina_history()`。
4. 超时：单次 15s 通过 `run_in_thread` 保护。

**验收**：至少 3 只不同指数的 ETF（如 A500 / 沪深300 / 黄金）的 RSI_14 返回真实值（≠50.0）。

---

### P0-2: 因子分回退逻辑 + 去除 meltdown

**目标**：因子分在价格数据不足时仍有区分度，meltdown 异常不阻断管道。

**方案 A——回退逻辑**：在 `factor_registry.py` 的 `compute()` 中，当 `fetch_history` 返回空数据时，回退到基于静态数据的评分：

```python
def _scale_score(raw: float) -> float:
    """将原始值映射到 0~1 区间，使用 sigmoid 近似"""
    import math
    return 1.0 / (1.0 + math.exp(-raw * 1e-9))  # 对大规模金额值生效

def _fallback_score(symbol: str, meta: dict) -> dict:
    """静态数据回退评分（当历史行情不可用时）"""
    amount = float(meta.get("amount", 0) or 0)
    scale = float(meta.get("fund_scale", 0) or 0) 
    premium = float(meta.get("premium_discount", 0) or 0)
    return {
        "technical": _scale_score(amount * 0.6 + scale * 0.4),
        "momentum": _scale_score(amount * 0.3),
        "valuation": _scale_score(abs(premium) * (-1)),       # 折溢价越小越好
        "sentiment": _scale_score(scale * 0.5),
    }
```

**方案 B——去除 meltdown**：将 `compute()` 的 meltdown 守卫（line 789-804）改为**日志警告 + 返回默认值**而非抛出异常：

```python
# 原代码：raise RuntimeError(...)
# 改为：
logger.error("[factor] severe meltdown: ...")
factor_scores[sym] = _fallback_score(sym, meta)
return factor_scores
```

**代码位置**：`backend/app/factors/factor_registry.py`
- compute() → 加入 `_fetch_market_data` 失败时的 fallback 调用
- line 789-804 → meltdown 守卫改为日志 + 回退

---

### P0-3: tracked_index 回填与去重

**目标**：同指数多只 ETF 只保留规模最大的一只；池中标的分类正确。

**方案**：

**A. 合并 East Money 数据**（`etf_scanner.py`）
在 `fetch_all_etfs_base()` 中，当 Sina+gtimg（Tier 1）返回后，异步并行拉取 East Money 数据（Tier 3），将 `f168`（tracked_index）、`f20`（基金规模）等字段合并到已返回的 ETF 记录中。

```python
# 在 fetch_all_etfs_base() 中
base_etfs = await tier1()  # Sina+gtimg
em_etfs = await tier3()    # East Money（含 tracked_index）
# 按 symbol 合并
merged = {}
for e in base_etfs:
    merged[e["symbol"]] = e
for e in em_etfs:
    if e["symbol"] in merged:
        merged[e["symbol"]]["tracked_index"] = e.get("f168", "")
```

**B. 名称模糊匹配去重**（`pool_manager.py`）
在 `_deduplicate_by_index()` 中，当 `tracked_index` 为空时，用 `name` 字段中的指数关键词做去重：

```python
INDEX_KEYWORDS = ["A500", "沪深300", "中证500", "科创板", "创业板",
                   "红利", "半导体", "芯片", "医药", "新能源",
                   "消费", "军工", "证券", "银行", "黄金", "国债"]
def _extract_index_keyword(name: str) -> str:
    for kw in INDEX_KEYWORDS:
        if kw in name:
            return kw
    return ""
```

---

### P0-4: 因子分缓存失效判断

**目标**：因子计算失败的结果不缓存，下次请求重新计算。

**方案**：在 `portfolio_service.py:371-374` 的 `_strategy_check_cache` 缓存命中判断中，增加结果有效性检查：

```python
if cache_hit:
    cached = cache[cache_key]
    # 如果缓存的结果是空 dict 或包含错误标记，视为 cache miss
    if cached and not _is_failed_result(cached):
        return cached

def _is_failed_result(result: dict) -> bool:
    """判断因子结果是否为失败（全部为空或含错误标记）"""
    if not result:
        return True
    for sym, scores in result.items():
        if scores and any(v != 0 for v in scores.values()):
            return False
    return True  # 所有标的因子分全为零
```

---

### P1-1: 三策略差异化

**目标**：防御型/平衡型/进攻型在标的组成上可明显区分。

**方案**：

**(a) 核心层差异化**
| 策略 | core max_count |
|------|:-------------:|
| 防御型 | 2 |
| 平衡型 | 3 |
| 进攻型 | 3 |

**(b) 卫星层裁剪**
```python
# allocation_engine.py _filter_satellite_by_profile()
KEEP_RATIO = {
    "defensive": 0.5,   # 只保留 50%
    "aggressive": 0.6,  # 只保留 60%
    "balanced": 1.0,     # 保留全部
}
# 评分后只保留 top K%
keep_count = max(1, int(len(scored) * KEEP_RATIO[profile_key]))
return [item for _, item in scored[:keep_count]]
```

**(c) 防御层差异化**
| 策略 | defense max_count |
|------|:-------------:|
| 防御型 | 2 |
| 平衡型 | 1 |
| 进攻型 | 1 |

**(d) 核心层防御过滤**
防御型方案的核心层 `_select_and_weight()` 前也做防御性评分（降低 momentum 权重、提高 valuation 权重）。

**影响范围**：`backend/app/engine/allocation_engine.py`

---

### P1-2: 防御层分类修复

**目标**：防御层包含黄金/国债等真正防御资产。

**方案**：

在 `pool_manager.py` 的 `_refresh_impl()` 中修改层分配逻辑：

```python
# 原代码（line 265）：
elif base_layer == "defense" or industry in ("商品", "固收", "跨境"):
    target = LAYER_DEFENSE

# 改为：
elif base_layer == "defense" or industry in ("商品", "固收"):
    target = LAYER_DEFENSE
elif industry == "跨境":
    target = LAYER_SATELLITE  # 跨境 → 卫星层
```

---

### P1-3: 强制标的进入分配

**目标**：`MANDATORY_CODES` 中的标的出现在每套策略的分配中。

**方案**：在 `_select_and_weight()` 中增加强制标的逻辑：

```python
# 在 _select_and_weight() 的头部
MANDATORY_MIN_WEIGHT = 0.05
mandatory_assignments = []
for c in candidates:
    if c.get("symbol", "") in MANDATORY_CODES:
        mandatory_assignments.append({
            "symbol": c["symbol"],
            "name": c.get("name", ""),
            "layer": layer,
            "weight": MANDATORY_MIN_WEIGHT,
            "selection_rationale": f"强制保留：{c.get('name', '')}作为{layer}层核心配置",
        })
        # 从 budget 和 candidates 中扣除
        budget -= MANDATORY_MIN_WEIGHT

# 剩余 budget 分配给其他候选
if budget <= 0:
    return mandatory_assignments
```

**注意**：需要在 `strategy_design.py` 中将 `MANDATORY_CODES` 暴露到引擎层。

---

### P1-4: risk_controls.py 拼接 bug 修复

**目标**：入选理由字符串正确拼接。

**方案**：修复 `filter_extreme_drawdown()` 的运算符优先级问题：

```python
# 在 risk_controls.py 中 line 43-46
# 原代码（错误）：
rationale += f"近一月涨跌{ret_1m:.1%}" if isinstance(ret_1m, (int, float)) else ""

# 改为：
rationale = rationale + (f"近一月涨跌{ret_1m:.1%}" if isinstance(ret_1m, (int, float)) else "")
```

---

### P1-5: E2E 脚本超时配置修正

**目标**：消除假阳性失败，使 E2E 结果准确反映系统状态。

**方案**：
```python
# verify_e2e.py 修改点

# 1. POST 超时 30s → 60s（给高负载下的请求队列留出时间）
r = requests.post(f"{BASE}/api/v1/portfolio/design-async", ..., timeout=60)

# 2. 异步设计轮询 180s → 240s
deadline = time.time() + 240

# 3. 轮询超时后做一次最终确认
if not completed:
    last_check = requests.get(f"{BASE}/api/v1/portfolio/tasks/{task_id}", timeout=10)
    if last_check.status_code == 200 and last_check.json()["status"] == "completed":
        check("异步设计任务完成（轮询超时后确认）", True)
        completed = True
if not completed:
    check("异步设计超时", False, "240s 内未完成")
```

**影响范围**：`backend/scripts/verify_e2e.py`

---

### P1-6: 外部数据源熔断保护

**目标**：不可用数据源快速失败，不阻塞线程池。

**方案 A——`sentiment_fetcher.py` push2 调用降级**：将 `timeout=10` 降到 `timeout=3`，减少等待时间：
```python
# sentiment_fetcher.py 中 push2 调用
resp = urllib.request.urlopen(req, timeout=3)  # 10→3
```

**方案 B——`sentiment_fetcher.py asyncio.gather` 超时保护**：当前 `asyncio.to_thread` 超时 15s，可压到 8s：
```python
advance, north, margin = await asyncio.gather(
    asyncio.wait_for(asyncio.to_thread(fetch_advance_decline_ratio), timeout=8),  # 15→8
    ...
)
```

**影响范围**：`backend/app/fetchers/sentiment_fetcher.py`

---

### P2-1: 策略检查因子数据管道

**目标**：`holdings_analysis` 包含真实的因子摘要。

**方案**：

1. **注入 factor_matrix**：在 `strategy_check_pipeline()` 中调用 `pool_manager.get_factor_matrix()`：
```python
# strategy_check_worker.py 中
factor_matrix = pool_manager.get_factor_matrix()
result = await strategy_check(capital, holdings, factor_matrix=factor_matrix)
```

2. **传递到 LLM prompt**：在 `portfolio_service.strategy_check()` 中，将 factor_matrix 数据写入每个 holding 的 `factor_breakdown` 字段。

3. **避免重复计算**：如果 factor_matrix 已包含当前所有持仓的数据，直接使用，无需再调用 `factor_registry.compute()`。

---

### P2-2: holdings_analysis 注入 weight

**目标**：`holdings_analysis` 中每条记录有正确的权重值。

**方案**：

**方式 A（推荐）**：在 `strategy_check_worker.py` 中，LLM 返回后做后处理：

```python
# strategy_check_worker.py line 60-70
holdings_analysis = result.get("holdings_analysis", [])
# 从原始持仓数据回填 weight
for ha in holdings_analysis:
    sym = ha.get("symbol", "")
    holding = next((h for h in holdings if h.get("symbol") == sym), None)
    if holding and ha.get("weight") is None:
        ha["weight"] = holding.get("target_weight")
```

**方式 B**：修改 `strategy_check.md` prompt，在 `holdings_analysis` schema 中加入 `weight` 字段。

---

### P2-3: 策略检查摘要增强

**目标**：summary ≥ 150 字，suggestions 包含买卖双向。

**方案**：修改 `strategy_check` LLM prompt 增加硬约束：

```markdown
## 产出要求

### summary 必须包含：
1. 当前市场状态判断（引用 index_realtime 数据）
2. 持仓结构总体评价（集中度/行业分布）
3. 2-3 条具体调仓方向，按优先级排列

### suggestions 要求：
- 必须包含至少 2 条 increase/buy 建议
- 每条建议注明 confidence（high/medium/low）
- 对重复持仓（同指数不同产品）明确建议合并方向
```

---

### P2-4: target_weight 添加默认值

**目标**：新建持仓有合理的默认权重。

**方案**：在 `PortfolioETF` model 中设置默认值：

```python
# models/portfolio.py
target_weight: float = Field(default=0.05)  # 默认 5%
```

---

### P3-1: 补关键模块单测

**目标**：覆盖 4 个当前零测试的关键模块。

**方案**：

**(a) `risk_controls.py` 测试** — 最少 3 个用例：
```python
def test_remove_stale_candidates_preserves_fresh():
    """有效数据的标的不会被移除。"""
def test_filter_extreme_drawdown_rationale_not_corrupted():
    """drawdown filter 触发时入选理由字符串不损坏 ← 回归 P1-4 bug。"""
def test_apply_risk_controls_satellite_minnow_consolidated():
    """小权重卫星层标的被合并到 CASH。"""
```

**(b) `allocation_engine.py` 测试** — 最少 3 个用例：
```python
def test_defensive_vs_aggressive_symbols_differ():
    """防御型和进攻型的 ETF 标的集合至少 30% 不同。"""
def test_filter_satellite_reduces_candidates():
    """防御型过滤后卫星层候选数 < 原始候选数。"""
def test_mandatory_codes_included():
    """MANDATORY_CODES 在每套策略中均有分配。"""
```

**(c) `portfolio_service.strategy_check()` 测试** — 最少 2 个用例：
```python
async def test_strategy_check_returns_expected_structure():
    """返回结果包含 summary, suggestions, holdings_analysis, market_regime。"""
async def test_strategy_check_factor_data_injected():
    """给入有效因子数据时，holdings 中 factor_summary 非空。"""
```

**(d) `sentiment_fetcher.fetch_market_sentiment()` 测试** — 最少 1 个用例：
```python
def test_fetch_market_sentiment_returns_default_on_failure():
    """数据源超时时返回中性默认值，不抛异常。"""
```

**影响范围**：`tests/test_risk_controls.py`, `tests/test_allocation_engine.py`, `tests/test_strategy_check.py`, `tests/test_sentiment_fetcher.py`（均为新文件）

---

### P3-2: pre-commit 增加后端测试门禁

**目标**：`backend/` 变更时自动运行 `pytest -x`。

**方案**：在 `.githooks/pre-commit` 中增加后端检测逻辑：

```bash
# pre-commit 脚本新增
BACKEND_STAGED=$(git diff --cached --name-only --diff-filter=ACM -- 'backend/*' 2>/dev/null || true)
if [ -n "$BACKEND_STAGED" ]; then
    echo "[pre-commit] 检测到后端文件变更，正在执行 pytest -x ..."
    cd backend
    if python -m pytest -x 2>&1; then
        echo "[pre-commit] ✅ pytest 通过"
        cd ..
    else
        cd ..
        echo "[pre-commit] ❌ pytest 失败，请修复后重试"
        echo "  如需跳过: SKIP_BACKEND_TESTS=1 git commit ..."
        exit 1
    fi
fi
```

**影响范围**：`.githooks/pre-commit`

---

### P3-3: E2E 增加数据质量断言

**目标**：`verify_e2e.py` 能检测内容性缺陷。

**方案**：在 `section_portfolio()` 末尾增加以下检查：
```python
# 1. 因子分区分度检查
factor_scores = []
for strategy in strategies:
    for alloc in strategy.get("allocations", []):
        fs = alloc.get("factor_score", None)
        if fs is not None:
            factor_scores.append(fs)
if len(factor_scores) > 2:
    variance = sum((x - mean(factor_scores))**2 for x in factor_scores) / len(factor_scores)
    check("因子分方差 > 0.01（有区分度）", variance > 0.01, f"variance={variance:.4f}")

# 2. 三方案差异化检查
strategy_symbols = [set(a.get("symbol") for a in s.get("allocations", []) if a.get("symbol") != "CASH") for s in strategies]
if len(strategy_symbols) >= 2:
    diff_ratio = len(strategy_symbols[0] - strategy_symbols[1]) / max(len(strategy_symbols[0]), 1)
    check("三方案标的差异度 > 30%", diff_ratio > 0.3, f"{diff_ratio:.0%}")

# 3. 防御层包含防御资产
for i, s in enumerate(strategies):
    def_etfs = [a for a in s.get("allocations", []) if a.get("layer") == "defense"]
    def_symbols = {a.get("symbol") for a in def_etfs}
    if def_symbols:
        has_defensive = "518880" in def_symbols or "511090" in def_symbols
        check(f"策略{i}:防御层含黄金/国债", has_defensive, str(def_symbols))
```

**影响范围**：`backend/scripts/verify_e2e.py`

---

### P3-4: 数据管道健全性监控脚本

**目标**：定期验证从数据源到策略输出的完整链路，记录关键指标。

**方案**：新建 `scripts/data_health_check.py`，每周运行一次：
```python
# 检查内容
- factor_registry.compute() 对 10 只常见 ETF 的因子分方差 > 0.01
- pool_manager.get_pool() 各层候选数满足 core ≥ 3, sat ≥ 5, def ≥ 2
- fetch_history("510300", "A", "daily") 返回近 60 个交易日数据
- 两次连续调用 get_factor_matrix() 的结果差异 < 5%（缓存命中验证）
```

**影响范围**：新增 `backend/scripts/data_health_check.py`

---

## 4. 实施路线图

### 当前实施状态

| 映射到 master-plan Phase | 本文档对应项 | 状态 | 关键 commit 或说明 |
|------------------------|------------|:----:|-------------------|
| Phase 0.7 | P0-3 部分（tracked_index 链）、P1-1 部分（差异化） | ✅ 已实施 | `d478f12` |
| Phase 0.8 | P1-5（E2E 超时调整）、P3-3 部分（verify_e2e 质量增强） | ✅ 已实施 | `ad3e12eb` |
| Phase 0.9 | P1-6（线程池 + 外部数据源熔断保护）、P3-1 部分（async_boundaries 测试） | ✅ 已实施 | `2be9ccb` |
| — | P0-1（_etf_history） | ✅ 已提交 | `53acbfa` |
| — | P0-2（meltdown→warning） | ✅ 已提交 | `53acbfa` |
| — | P0-3 剩余（INDEX_KEYWORDS） | ✅ 已提交 | `53acbfa` |
| — | P3（markdown.js marked 库替换） | ✅ 已提交 | `53acbfa` |
| **Phase 2.1** | **P0-4→S1-A(TTL) + P1-1 + P1-3 + P2-1→S2 + P3-1~P3-4 + china_market import 修复 + 新增未规划 6 项** | **✅ 全部完成** | `5116681` `53acbfa` `ef3de11` `17e9cab` `a5028fa` `ac6dd81` `afaea68` `783e188` `c72b0ac` `e6264ee` |
| **Phase 2.2** | **数据管道根因修复（china_market import 修复、C2风偏增强、B3b去重、decode_df 逐格修复、DB编码修复、test teardown 防护等 15 项）** | **✅ 全部完成** | commits `e6264ee`~`5f484e6`；详情见 master-plan v5.0 §Phase 2.2 |
| **Phase 1.1 待实施** | **5 项**：P1-2、P1-4、P2-2、P2-3、P2-4 | **⚠️ 待实施** | 见 master-plan Phase 1.1.10~1.1.14 |

### Phase 2.1 实施完成项（映射到 master-plan）

✅ **以下均已完成**（见 master-plan v5.0 §Phase 2.1 + §Phase 2.2）：

| # | 任务 | 状态 | 提交 |
|---|------|:----:|:----:|
| 2.1.0 | P1-1 三策略差异化（C1 + profile权重 + C2风偏分 + B3b去重） | ✅ 已实施 | `d478f12` `5116681` `17e9cab` |
| 2.1.1 | P1-2 ~~防御层分类修复~~ → **已转入 Phase 1.1** | ⏳ 待实施 | — |
| 2.1.2 | P1-3 强制标的进入分配（MANDATORY_MIN_WEIGHT 5%） | ✅ 已实施 | `5116681` |
| 2.1.3 | P0-4 → S1-A TTL 缓存（pool_manager 60s） | ✅ 已实施 | `53acbfa` |
| 2.1.4 | P1-4 ~~拼接 bug 修复~~ → **已转入 Phase 1.1** | ⏳ 待实施 | — |
| 2.1.5-2.1.8 | P2-1→S2 混合归一化（因子分 ×5 + profile权重 + 强制下限） | ✅ 已实施 | `5116681` |
| 2.1.9 | P3-1 补关键模块单测（test_data_health.py + DQ 门禁） | ✅ 已实施 | `a5028fa` `1e63eab` |
| 2.1.10 | P3-2 pre-commit 后端测试门禁（+API 覆盖检查） | ✅ 已实施 | `c72b0ac` |
| 2.1.11 | P3-3 E2E 数据质量断言（verify_e2e 增强） | ✅ 已实施 | `afaea68` |
| 2.1.12 | P3-4 数据管道健全性脚本（data_health_check.py） | ✅ 已实施 | `ac6dd81` |

**新增未规划项（已落地）**：
- F10 tracked_index 补充（`enrich_tracked_indices()` + JSON 缓存）`17e9cab`
- C2 名称风偏基准分（估值稀疏时按名称 +/- 补偿）`17e9cab`
- 新闻情感桥接（pool_manager step 3c → sentiment 非零）`a5028fa`
- IOPV 批量 + change_pct 因子注册 `783e188`
- DQ 测试门禁（DQ1-DQ5 防止回归）`a5028fa`
- verify_design.py 验证管道 `afaea68`
- china_market.py import 错误根因修复（所有 26 因子从 0→非零）`e6264ee`

**Phase 1.1 待实施**（5 项，~20 行，~1h）：
- P1-2 防御层分类修复（跨境→卫星层，~3 行）
- P1-4 risk_controls 拼接 bug 修复（~1 行）
- P2-2 holdings_analysis 注入 weight 字段（~5 行）
- P2-3 策略检查摘要增强（~10 行）
- P2-4 target_weight 默认值 0.0 修复（~1 行）

验证: pytest 全 PASS + verify_e2e 含数据质量断言全 PASS + DQ 门禁全 PASS

---

## 5. 不在本次范围

以下问题已识别但本次不修复，供后续参考：
1. **因子定义文件 `factor_definitions.yaml` 优化** — 当前定义的 167+ 因子中部分重复或不可计算；待数据源修复后评估因子有效性。
2. **前端方案卡片 UI 增强** — 方案卡片当前仅展示权重和入选理由，缺少因子分可视化、风险指标仪表盘。
3. **回测框架** — 设计完成后无法回测验证历史表现；需单独的回测模块。
4. **多语言报告** — 当前仅支持中文报告，未涉及英文或其他语言。

---

## 6. 验收标准

### ✅ Phase 0 通过条件（已全部通过）

- [x] **P0-1**: 至少 3 只不同指数 ETF（如 A500 / 沪深300 / 黄金）的 `RSI_14` ≠ 50.0 — `53acbfa` ✅
- [x] **P0-1**: 后端日志不再出现 `fetch_history failed: empty data` 对 ETF 的警告 — `53acbfa` ✅
- [x] **P0-2**: `factor_registry.compute()` 在价格数据缺失时不抛出 RuntimeError — `53acbfa` ✅
- [x] **P0-2**: 即使数据缺失，不同 ETF 的 `technical` 值至少有 5% 的差异 — `e6264ee` ✅
- [x] **P0-3**: 候选池中同指数（如"A500"）的 ETF 不超过 2 只 — `17e9cab` B3b dedup ✅
- [x] **P0-3**: 510300(沪深300) 存在于 core 层候选池中 — `53acbfa` ✅
- [x] **P0-4**: 因子计算失败后 60s 内再次请求能触发重新计算 — `53acbfa` S1-A TTL ✅
- [x] **P0 集成**: `verify_e2e.py` 全 PASS（异步设计超时可接受）— `afaea68` ✅

### ⚠️ Phase 1 通过条件（**5/7 已通过**，P1-2 + P1-4 待实施）

- [x] **P1-1**: 防御型的 ETF 标的集合 ≠ 平衡型 ≠ 进攻型（至少 30% 不同）— C1 + profile权重 + C2风偏分 ≈ 50%+ 不同 ✅
- [x] **P1-1**: 防御型 core 层配置少于进攻型 satellite 层 — profile_weight 控制 ✅
- [ ] **P1-2**: 防御层至少包含 518880(黄金ETF) 或 511090(30年国债ETF) — 待实施（Phase 1.1.10）
- [ ] **P1-2**: 防御层不包含香港 ETF（520xxx 系列）— 待实施（Phase 1.1.10）
- [x] **P1-3**: 510300(沪深300) 出现在至少 2 套策略的分配中 — `5116681` MANDATORY_MIN_WEIGHT ✅
- [x] **P1-3**: 518880(黄金) 出现在防御型方案的防御层中 — `5116681` ✅
- [ ] **P1-4**: 触发 drawdown filter 的 ETF 入选理由字符串不损坏 — 待实施（Phase 1.1.11）

### ⚠️ Phase 2 通过条件（**1/5 已通过**，4 项待实施）

- [x] **P2-1**: `holdings_analysis` 中至少 50% 持仓有非空 `factor_summary` — `5116681` S2 混合归一化 ✅
- [ ] **P2-2**: `holdings_analysis` 中每条记录有非空 `weight` 值 — 待实施（Phase 1.1.12）
- [ ] **P2-3**: `summary` ≥ 150 字，包含市场状态 + 持仓评价 + 调仓方向 — 待实施（Phase 1.1.13）
- [ ] **P2-3**: `suggestions` 包含至少 2 条 increase/buy 建议，注明 confidence — 待实施（Phase 1.1.13）
- [ ] **P2-4**: 新建持仓 `target_weight` 默认为 0.05（5%）— 待实施（Phase 1.1.14）

### 验证脚本

每次 Phase 完成后，运行以下命令验证：
```bash
# P0 集成验证
cd backend && python scripts/verify_e2e.py --module portfolio

# P1 方案差异化验证（需编写独立脚本）
python -c "from app.engine.allocation_engine import allocate; ..."

# P2 策略检查验证
cd backend && python scripts/verify_e2e.py --module portfolio | findstr "holdings|summary|suggestions"
```

---

## 7. 风险评估与回滚策略

### Phase 0: 数据管道修复
| 风险 | 概率 | 影响 | 缓解措施 |
|------|:---:|:----:|---------|
| ETF 历史数据 API (`ak.fund_etf_hist_em`) 不可用 | Medium | 回退到 Sina，数据可能仍不足 | 代码已含 fallback 链，仅新增 ETF 专用路径，不影响现有降级逻辑 |
| 去重导致候选池标的减少过多 | Medium | 核心层只剩 1-2 只标的 | `_deduplicate_by_index()` 的 `KEEP_TOP` 最大限制可调（从 1 调到 2-3） |
| 因子分缓存修复引入死循环 | Low | 缓存永不命中 | TTL 不变，仅增加"失败结果不缓存"判断，不影响正常缓存逻辑 |

**回滚命令**：
```bash
git checkout main -- backend/app/fetchers/china_market.py
git checkout main -- backend/app/factors/factor_registry.py
git checkout main -- backend/app/services/pool_manager.py
git checkout main -- backend/app/services/portfolio_service.py
```

### Phase 1: 策略引擎修复
| 风险 | 概率 | 影响 | 缓解措施 |
|------|:---:|:----:|---------|
| 强制标的权重挤占其他标的预算 | High | 其他标的权重被压低 | 强制权重设 5%（低值），不侵占超过 10% 的层预算 |
| 卫星层裁剪导致某方案无可选标的 | Low | 返回空分配 | `max(1, keep_count)` 保证至少保留 1 只候选 |
| 防御层分类修改影响现有持仓 | Medium | 已有设计的防御层可能变化 | 仅影响新提交的设计，历史记录不变 |

**回滚命令**：
```bash
git checkout main -- backend/app/engine/allocation_engine.py
git checkout main -- backend/app/engine/risk_controls.py
git checkout main -- backend/app/services/pool_manager.py
```

### Phase 2: 策略检查修复
| 风险 | 概率 | 影响 | 缓解措施 |
|------|:---:|:----:|---------|
| LLM prompt 修改导致输出格式不一致 | Medium | 前端解析失败 | 修改 prompt 后运行现有单测 `pytest tests/` |
| weight 后处理冲突（DB 和 LLM 值不同） | Low | 显示异常 | 后处理优先于 LLM 输出，增加 `weight_source` 标记 |

**回滚命令**：
```bash
git checkout main -- backend/app/services/portfolio_service.py
git checkout main -- backend/app/tasks/strategy_check_worker.py
git checkout main -- backend/app/analysis/llm.py
git checkout main -- backend/app/analysis/prompts/v1/strategy_check.md
```

### 整体回滚策略
- 每个 Phase 的代码修改**可独立回滚**，不依赖其他 Phase。
- Phase 0 回滚会导致 Phase 1/2 无法正常工作（因为依赖数据管道），但不会损坏数据库。
- 数据库迁移（P2-4 model 修改）需手动 `ALTER TABLE` 回退。

---

## 8. 附录：关键代码路径

### 因子计算路径
```
factor_registry.compute(symbols)  [factor_registry.py:690]
  → _fetch_market_data(symbols)   [factor_registry.py:647]
    → fetch_history(sym, "A", "daily")  [china_market.py:746]
      → _mootdx_history()          [china_market.py:118]    ← 不支持 ETF
      → _akshare_history_fallback() [china_market.py:146]   ← 股票 API
      → _sina_history()             [china_market.py:761]   ← 数据不足
  → RSI/SMA/MACD 计算              [factor_registry.py:70-160]  ← 全部回退默认值
  → aggregate_factor_scores()       [factor_registry.py:601]
```

### 设计分配路径
```
generate_enhanced_design()          [strategy_design.py:30]
  → pool_manager.refresh()          [pool_manager.py:145]
    → scanner.full_pipeline()        [etf_scanner.py:432]
      → fetch_all_etfs_base()         → Sina → East Money
      → classify_etf()                → 确定行业/层
    → factor_registry.compute()       → 计算因子分
    → _deduplicate_by_index()         → 去重 ← tracked_index 丢失
    → _ensure_mandatory()             → 强制标的
  → engine_allocate()                [allocation_engine.py:185]
    → _filter_satellite_by_profile()  → 排序但不裁剪
    → _select_and_weight()            → 选 top-N（相同因子分→相同标的）
  → apply_risk_controls()            [risk_controls.py:171]
    → line 43-46: 拼接 bug
```

### 策略检查路径
```
strategy_check_pipeline()            [strategy_check_worker.py:19]
  → strategy_check()                  [portfolio_service.py:328]
    → factor_registry.compute()       → meltdown → raise → {}  ← 上游 bug
    → generate_strategy_check_report() [llm.py:706]
      → prompt: "无因子数据" → LLM 保守输出
  → 持久化到 DB                       → factors_json 存储空数据 → cache 污染
```

---

## 9. 测试防护体系缺口分析

### 9.1 现有防护层总览

| 层 | 机制 | 覆盖范围 | 验收标准类型 |
|:--:|------|---------|:----------:|
| **pre-commit** | `.githooks/pre-commit` | API密钥泄露检测 + 前端 `npm run build` | 语法级 |
| **后端单测** | 38 个 `tests/test_*.py` 文件 | 各模块函数逻辑（全部外部调用 mock） | 功能级 |
| **前端单测** | 6 个 `src/test/*.spec.js` 文件 | Vue 组件逻辑 | 功能级 |
| **E2E 校验** | `scripts/verify_e2e.py` | HTTP 端点存活 + 任务开始/完成 | 连通级 |

### 9.2 逐项对照：12 个漏洞为何未被捕获

#### P0 层（数据管道）— 4 项

| 漏洞 | 相关测试 | 测试做了什么 | 为什么没发现 |
|------|---------|-------------|-------------|
| mootdx 不支持 ETF | `test_factor_registry.py` | 直接构造 `close=[...]` 传计算函数 | **从不测试数据源到计算函数的完整链路**。 `_fetch_market_data()` → `fetch_history()` → `_mootdx_history()` 整条链在 mock 之下运行，真实数据源从未被调用 |
| 因子分全部相同 | `test_pool_manager.py` | Mock `factor_registry.compute()` 返回预赋值的差异化因子分 | mock 数据是**人工构造的有区分度样本**，从不模拟真实数据源的塌陷输出 |
| meltdown 异常 | `test_strategy_check_async.py` | **仅测试模块导入和 model schema**（47 行，0 功能测试） | `portfolio_service.strategy_check()` 这个 328 行的核心函数 **有 0 行测试覆盖** |
| 因子分缓存污染 | 无 | — | 缓存模块无独立测试；E2E 也不检测重复请求后的结果变化 |

#### P1 层（策略引擎）— 4 项

| 漏洞 | 相关测试 | 测试做了什么 | 为什么没发现 |
|------|---------|-------------|-------------|
| 三策略无差异化 | `test_design_pipeline_integration.py` | Mock `generate_enhanced_design()` 整体返回预置差异化策略 | **从不测试 `allocation_engine.allocate()` 的真实输出**；mock 跳过了整个引擎 |
| 防御层分类错误 | `test_pool_manager.py` | Mock classifier 返回 `商品/固收` 等正确标签 | 从不测试 real scanner 传给 classifier 的输入（Sina 源的 `industry/tracked_index` 缺失） |
| 强制标的未分配 | `test_design_pipeline_integration.py` | Mock 的策略总是包含 510300 | mock 数据**承诺了**正确结果，所以测试永远 pass |
| risk_controls bug | 无 | — | `risk_controls.py` 无独立测试文件 |

#### P2 层（策略检查）— 4 项

| 漏洞 | 相关测试 | 测试做了什么 | 为什么没发现 |
|------|---------|-------------|-------------|
| 因子数据缺失 | `test_strategy_check_async.py` | 仅导入模型 + 检查路由注册 | **整个 strategy_check 函数零测试覆盖** |
| weight 字段缺失 | 同上 | 仅检查 `to_dict()` 输出格式 | `holdings_analysis` schema 中的 `weight` 字段缺失不被任何测试断言 |
| 摘要过短 | 无 | — | 无 LLM 输出质量断言 |
| target_weight=0 | 无 | — | model schema 无默认值测试 |

### 9.3 根因模式

```
                理想数据流 (测试路径)              真实数据流 (生产路径)
                ──────────────────               ──────────────────
                mock fixture 构造                  mootdx/akshare/Sina
                有区分度的因子分                       ↓ (ETF不支持)
                       ↓                        factor_registry 收到空数据
                factor_registry.compute()               ↓
                (直接构造 close[] 数组)          所有因子回退到默认值 → 完全相同
                       ↓                                ↓
                引擎获得差异化因子分               引擎获得完全相同的因子分
                       ↓                                ↓
                三策略输出不同 (✅ test pass)     三策略输出相同 (❌ 线上)
```

**核心问题**：测试 **只验证了"当输入是正确的，逻辑是否正确"**，但**从未验证"真实输入是否真的正确"**。

### 9.4 具体缺口

1. **mock 链过长** — `test_design_pipeline_integration.py` 把 `generate_enhanced_design` 整体 mock 了，engine 层、pool_manager 层、factor_registry 层的数据质量**全部不在测试范围内**
2. **缺少集成测试** — 没有测试把 `fetch_history` → `compute` → `allocate` 串起来，用真实数据源输出做端到端验证
3. **缺少数据质量断言** — 没有任何测试检查"因子分是否具有区分度"、"三方案是否真的不同"
4. **pre-commit 未跑后端测试** — 只跑了前端构建检查，后端 `pytest` 需要手动执行
5. **E2E 只测连通性** — `verify_e2e.py` 检查 200 状态码和任务完成，但不检查数据内容的**合理性**
6. **关键的 `strategy_check()` 零测试覆盖** — 这是 328 行的核心业务函数，没有任何一行测试代码

### 9.5 建议的测试防御增强

#### 短期（9.4 缺口的"止痛药"）
- [ ] 补 `risk_controls.py` 单测 — 确认运算符优先级 bug 修复后有回归测试
- [ ] 补 `allocation_engine.py` 单测 — `allocate()` 对相同因子分应输出可区分的三套方案
- [ ] 补 `portfolio_service.strategy_check()` 最小功能测试 — mock 因子数据 + 验证输出结构

#### 中期（Phase 0-1 实施后）
- [ ] 补 `_fetch_market_data()` 集成测试 — 用真实 ETF 代码调用，验证 RSI ≠ 50.0
- [ ] E2E 增加数据质量断言 — 在 `verify_e2e.py` 中检查：因子分方差 > 0.01、三方案标的差异度 > 30%

#### 长期
- [ ] pre-commit 增加后端测试门禁 — 检测 frontend/ 变更时跑 `npm run build`，检测 backend/ 变更时跑 `pytest -x backend/tests/`
- [ ] 引入"数据管道健全性测试" — 每周运行一次从真实数据源到策略输出的完整链路，记录因子分分布和方案差异度，超阈值告警

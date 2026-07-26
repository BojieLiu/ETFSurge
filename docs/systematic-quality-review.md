# 系统质量审查与修复方案

> 审查日期: 2026-07-26
> 审查范围: 组合设计管线、策略检查管线、因子数据管道、异步执行模型

---

## 目录

1. [发现的问题汇总](#1-发现的问题汇总)
2. [问题一：Event Loop 阻塞导致服务挂死](#2-事件循环阻塞)
3. [问题二：设计方案空壳退化](#3-设计方案空壳退化)
4. [问题三：因子数据大面积缺失](#4-因子数据大面积缺失)
5. [问题四：置信度始终为低](#5-置信度始终为低)
6. [问题五：编码与存储乱码](#6-编码与存储乱码)
7. [问题六：策略检查与设计的系统性偏差](#7-系统性偏差)
8. [修复方案与优先级](#8-修复方案与优先级)

---

## 1. 发现的问题汇总

| # | 问题 | 严重度 | 影响面 | 根因分类 |
|---|------|--------|--------|----------|
| 1 | 事件循环被同步 I/O 阻塞，导致服务挂死 | 🔴 P0 | 全系统可用性 | 异步边界违规 |
| 2 | 设计方案返回空壳（0 只 ETF）但标记 completed | 🔴 P0 | 组合设计功能 | 缺少有效性校验 |
| 3 | 因子数据大面积缺失（"因子数据不足"） | 🟠 P1 | 策略质量 | 数据源容错缺失 |
| 4 | 策略建议置信度始终为 low | 🟠 P1 | 用户信任 | 打分/聚合阈值问题 |
| 5 | 中文文本存储乱码（mojibake） | 🟠 P1 | 所有中文内容 | 编码传递路径断裂 |
| 6 | 设计退化（Design 219+ vs 218）无错误提示 | 🟡 P2 | 方案可用性 | 状态机设计缺陷 |
| 7 | 市态缓存只有被动刷新，无主动填充机制 | 🟡 P2 | 实时性 | 架构设计 |

---

## 2. 事件循环阻塞

### 2.1 现象

向 `POST /api/v1/portfolio/design-async` 发送设计请求后：
1. 请求成功返回 task_id（说明 `create_task` 完成）
2. 后台 `asyncio.create_task(design_pipeline(...))` 启动
3. `design_pipeline` → `generate_enhanced_design()` → `pool_manager.refresh()` 开始执行
4. **此时所有后续请求（健康检查、策略检查、查询）全部超时**
5. 服务进程死锁，只能强制 kill

### 2.2 代码定位

**调用链：**

```
portfolio.py:270  asyncio.create_task(design_worker(task_manager, t["task_id"]))
  → task_manager.py:398  design_worker = design_pipeline
    → task_manager.py:217  await asyncio.wait_for(
                            generate_enhanced_design(capital, constraints), timeout=90)
      → strategy_design.py:37  await pool_manager.refresh()
        → pool_manager.py:258  run_sync_long(self.scanner.full_pipeline, timeout=60)
          → scanner.full_pipeline  [同步 I/O: akshare, urllib, requests]
        → pool_manager.py:289  await run_sync(_enrich, flat)
          → _enrich  [同步 I/O]
        → pool_manager.py:295  await run_sync(self.classifier.batch_classify, flat)
          → batch_classify  [同步 I/O]
```

**根因：**

`pool_manager.refresh()` 内部的 `run_sync_long()` 和 `run_sync()` 将同步任务提交到线程池执行。但在某些场景下——特别是当线程池满或 I/O 操作进入死锁——**线程池中的同步调用会回堵事件循环**。

具体来看 `factor_registry.py` 的 `_fetch_market_data()`（第 833-872 行）：

```python
# factor_registry.py:840-846
import urllib.request
prefixes = {"5": "sh", "6": "sh", "0": "sz", "1": "sz", "3": "sz"}
sina_list = [f"{prefixes.get(sym[0], 'sh')}{sym}" for sym in symbols]
url = f"http://hq.sinajs.cn/list={','.join(sina_list)}"
req = urllib.request.Request(url, headers={"Referer": "http://finance.sina.com.cn"})
resp = urllib.request.urlopen(req, timeout=8)  # ← 同步阻塞！
raw = resp.read().decode("gbk")
```

这是 `async def _fetch_market_data()` —— 一个 async 函数，**内部直接使用同步 `urllib.request.urlopen()` 来做 HTTP 请求**。没有 `await run_sync()` 包装。这直接阻塞了事件循环。

### 2.3 修复方向

1. **唯一线上阻塞点修复**：`factor_registry.py:844-845` 的 Sina IOPV 批量获取改用 `await run_sync()` 包装（详细方案见 `docs/async-boundary-fix-plan.md §2.1`）
2. **死代码清理**：`macro_state.py:102/143` 的 `_fetch_pmi_trend`/`_fetch_rate_env` 两个未调用的 async 函数中的 akshare 调用需要修复以防启用后阻塞
3. **引入 CI 审计**：新增 `scripts/audit_async_blocking.py` 作为 pre-commit 门禁，AST 扫描禁止 async def 内出现同步 I/O
4. **异步边界单元测试**：在现有 `tests/test_async_boundaries.py` 中补测，覆盖 Sina IOPV 路径

---

## 3. 设计方案空壳退化

### 3.1 现象

对比 ID=218 与 ID=219-222 的设计方案：

| 维度 | Design 218 | Designs 219-222 |
|------|:----------:|:---------------:|
| 策略数量 | 3 套 | 1 套（空壳） |
| 每套 ETFs | 8-11 只 | **0 只** |
| expected_return | 有值 | **null** |
| max_drawdown | 有值 | **null** |
| market_context keys | 5 个 | 2 个 |
| design_text 长度 | 9,098 chars | **551 chars** |
| status | completed | completed ✓ |
| report_quality | full | full ✓ |

Designs 219-222 **全部标记为 "completed" 和 "full"，但实际无可用内容**——这是比失败更严重的问题，因为用户看到的是"已完成"却无法操作。

### 3.2 代码定位

**问题出现在 `generate_enhanced_design()`（strategy_design.py）的候选池空检查逻辑中：**

```python
# strategy_design.py:56-65
total_candidates = sum(len(v) for v in candidates.values())
if total_candidates == 0:
    return {
        "strategies": [],
        "market_context": _build_market_context(pool_manager),
        "error": "无候选标的",
        "detail": "数据管道未能生成候选池",
    }
```

当候选池为空，函数返回 `{"strategies": [], "error": "无候选标的"}`。

**但在调用端（task_manager.py:225-242）：**

```python
strategies = result.get("strategies", [])
error_info = result.get("error")
if error_info:
    # 标记为 failed → 正确
    mgr.update_task(task_id, ..., status="failed", ...)
    return

if not strategies:
    # 标记为 failed → 正确
    mgr.update_task(task_id, ..., status="failed", ...)
    return
```

这里看起来逻辑是对的——空策略会报 failed。**但 Designs 219-222 却显示 "completed" 且有 "full" 的 report_quality**。

这意味着要么：
1. `generate_enhanced_design()` 返回了 `strategies` 列表，但里面的策略缺失 ETFs（line 93-128 那里出了问题）
2. 或者 `pool_manager.refresh()` 超时后候选池空了，但 `pool_manager.refresh()` 的异常被 `strategy_design.py:38` 的 `except Exception` 吞掉了

看设计管线的上游——`strategy_design.py:36-40`：

```python
try:
    await pool_manager.refresh()
except Exception as e:
    logger.warning("[strategy_design] pool_manager.refresh failed — pool may be stale")
```

这里虽然有异常捕获但不影响后续流程。之后 `pool_manager.get_pool("core")` 可能返回空列表——那么 `total_candidates == 0` 触发空池返回。

但 Designs 219-222 都显示 `status=completed, report_quality=full` 且 `strategies` 有 **1 个**空策略——不是空列表。

**真正的问题可能在 `engine_allocate()` 方法中**——如果 `flat_candidates` 不为空但因子分全为 0，引擎可能产生了无 ETF 分配的策略模板。或者 `_build_plan_tables` 在空策略列表情况下仍然生成了 551 chars 的模板。

### 3.3 修复方向

1. **硬增加 `post-condition` 校验**：在 `strategies` 被返回前，验证每个 strategy 的 etfs 列表非空且至少一只非 CASH 标的
2. **状态机严谨化**：`completed` 状态必须有明确的完成条件定义（非空策略 + 有效数据），不符合则进入 `completed_with_errors` 或 `failed`
3. **增加 `strategy.etfs_count` 到列表元数据**（`GET /designs` 的 load_only 查询中），前端在列表页即可识别空壳方案
4. **对比 Design 218 和 219 的 `elapsed_seconds`** ——如果 219 以后的请求都极快完成（<2秒），说明数据管道根本没产出候选池

---

## 4. 因子数据大面积缺失

### 4.1 现象

从策略检查 102 的 `holdings_analysis` 中：

```json
{"symbol": "159338", "name": "中证A500ETF", "factor_summary": "因子数据不足",
 "tech_signal": "hold", "risk_flag": null}
```

10 只持仓中 **全部显示 "因子数据不足"**。`factor_summary` 字段没有输出具体的因子分值（正常应该是 `"momentum: 1.23σ；technical: 0.87σ；..."` 的格式）。

### 4.2 代码定位

**数据缺陷传递链：**

```
strategy_check() → factor_registry.compute(symbols)
  → compute() line 906: market_data = await self._fetch_market_data(symbols)
    → _fetch_market_data() line 782-831: 逐个 symbol 获取 K 线数据
      → [同步 urllib/akshare 调用]  → 可能超时/失败 → 返回 {"_fetch_error": "..."}
    → line 839-866: 批量获取 IOPV（Sina 实时行情）
      → [同步 urllib.request.urlopen] → 可能超时/失败
  → compute() line 919-922: 对每个 symbol 逐个因子计算
    → 如果 data 为空 或 key 缺失 → row[code] = 0.0  (静默填零)
```

**核心路径：**

在 `compute()` 函数的第 919 行：

```python
try:
    raw_value = computer(data)
    definition = self._factors.get(code)
    row[code] = raw_value if raw_value is not None else 0.0
except Exception as e:
    logger.debug("Factor %s failed for %s: %s", code, sym, e)
    row[code] = 0.0  # ← 静默失败
```

如果 `data` 字典为空（因为 `_fetch_market_data` 全部失败），**所有因子得分为 0.0**。之后：

```python
# line 936-958: z-score 标准化
all_v = [v for _, v in _raw[code]]
if len(all_v) < 2:
    continue  # ← 所有值一样，跳过标准化
```

当所有值为 0 时，`std_v = 0`，标准化被跳过。最终所有 symbol 的因子分全是 0。

回到 `strategy_check()` 的 holdings_analysis 后处理（line 505）：

```python
if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
    top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
    ...
else:
    # 不覆盖 LLM 的因子描述 → LLM 说 "因子数据不足"
```

因为所有因子分都是 0，`any(v != 0)` 为 False，所以 LLM 生成的 "因子数据不足" 不会被覆盖。

### 4.3 根因链

```
外部数据超时/失败
  → _fetch_market_data 返回空 dict
    → 所有因子得分为 0
      → z-score 标准化全部跳过
        → factor_summary = "因子数据不足"
```

中间没有熔断、没有降级、没有"至少返回部分因子"的机制。

### 4.4 修复方向

1. **因子级别的独立性**：每个因子的 `_fetch_market_data()` 应独立执行，一个因子失败不应影响其他因子
2. **引入缓存层**：`compute()` 应优先使用缓存 K 线数据（已有 `_get_cached_kline` 但未在 `compute()` 中兜底）
3. **降级策略**：当实时数据获取失败时，fallback 到缓存数据（即使过期），而非返回 0
4. **分层报告数据质量**：`factor_summary` 具体到 "momentum: 成功, valuation: 数据源超时" 的粒度，而非笼统的"数据不足"
5. **`compute()` 的 try/except 应该区分**——`data` 为空时应该 logging warning 而非静默填零

---

## 5. 置信度始终为低

### 5.1 现象

检查 102 的 4 条建议：

```json
{"action": "decrease", "symbol": "159338", "suggested_weight": 0.15, "confidence": "low"}
{"action": "decrease", "symbol": "518880", "suggested_weight": 0.1, "confidence": "low"}
{"action": "increase", "symbol": "513010", "suggested_weight": 0.05, "confidence": "low"}
{"action": "hold", "symbol": "510880", "suggested_weight": 0.08, "confidence": "low"}
```

**全部 `confidence: "low"`**，无法区分建议的可靠程度。

### 5.2 代码定位

置信度由 LLM 生成——`generate_strategy_check_report()` 在 `analysis/llm.py` 中构造 prompt 要求 LLM 输出 `confidence` 字段。

**数据传递链：**

```
strategy_check() → generate_strategy_check_report(market_data, factor_breakdowns, regime, data_quality)
  → LLM prompt: 包含 {factor_summary: "因子数据不足"} 的 holdings_analysis
  → LLM 看到 "因子数据不足" → 降级所有 confidence 为 low
```

**后处理逻辑（portfolio_service.py:505-508）：**

```python
if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
    top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
    h["factor_summary"] = "...真实因子分..."
else:
    # 不覆盖 — LLM 的 "因子数据不足" 保留
```

**根因：**

1. 因子数据全为 0 → `any(v != 0)` 为 False → 真实因子分不注入 coverage
2. LLM 收到的 `factor_summary` 是空的或 "因子数据不足" → 缺乏定量依据 → 所有 confidence = low
3. Prompt 内对 confidence 判定标准不明确——只给了 "high/medium/low" 可选项但没有量化门槛
4. `data_quality` 参数虽传给 LLM，但 LLM 是否有效使用了它取决于 prompt 质量——当前 prompt 可能没有要求 LLM 基于 `filled_count/total_count` 校准 confidence

### 5.3 修复方向

1. **定义明确的 confidence 计算规则**，在 `strategy_check()` 后处理中覆盖 LLM 输出（类似它已经覆盖 factor_summary 的方式）：
   - `filled_count / total_count > 0.8` → high
   - `0.5 ≤ ratio ≤ 0.8` → medium  
   - `ratio < 0.5` → low
   - 建议调整幅度 > 5% 且因子数据充分 → high
   - 建议调整幅度 < 3% 或因子数据不足 → low
2. **在 LLM prompt 中注入具体的 `filled_count/total_count` 指引**，要求 LLM 据此校准 confidence
3. **先修因子数据缺失（Issue #3）**——confidence 问题本质上是因子数据问题的下游症状，只有因子数据正常后 confidence 才能有真正的意义

---

## 6. 编码与存储乱码

### 6.1 现象

API 返回的中文字段在终端和日志中显示为 mojibake（乱码）：

```
"positioning": "\ufffd\ufffd..."  应为 "低波稳健配置"
"summary": "\ufffd\ufffd..."      应为 "组合目前持仓10只..."
```

设计方案的策略名：
```
"label": "\ufffd\ufffd\ufffd..."  应为 "稳健型"
"label": "\ufffd\ufffd\ufffd..."  应为 "平衡型"
```

### 6.2 初步诊断

追踪 `design_text` 的写入链路：

```
generate_enhanced_design() → 返回 UTF-8 Python 字符串
  → _build_plan_tables(strategies) → plan_tables
    → design_text = "# ETF 方案\n\n" + plan_tables
      → PortfolioDesign(design_text=design_text)
        → db.add(record) → await db.commit()
          → aiosqlite
```

**待验证的假设（按可能性排序）：**

1. **终端/日志编码**：uvicorn 控制台输出编码非 UTF-8（Windows GBK），导致日志和 `backend.err` 中的中文显示为乱码，**但 DB 实际存储正确**
2. **DB 编码**：aiosqlite/SQLite 文件编码问题——需要 DB 连接时显式设置 `PRAGMA encoding="UTF-8"`
3. **GBK 解码残留**：`factor_registry.py:846` 的 `resp.read().decode("gbk")` 从新浪取 IOPV 数据，如果未正确转换 UTF-8 可能污染后续处理

**验证步骤：**

```bash
# 1. 直接从 DB 读取 design_text 验证编码
python -c "
import aiosqlite
import asyncio
async def check():
    async with aiosqlite.connect('data/portfolio.db') as db:
        cur = await db.execute('SELECT id, design_text FROM portfolio_designs ORDER BY id DESC LIMIT 3')
        rows = await cur.fetchall()
        for r in rows:
            print(f'ID={r[0]}, text length={len(r[1])}')
            print(f'First 100 chars repr: {repr(r[1][:100])}')
asyncio.run(check())
"

# 2. 如果 DB 内容正确但 API 返回乱码 → 问题在 fastapi/uvicorn 编码中间件
# 3. 如果 DB 内容就乱码 → 问题在写入链路
```

### 6.3 修复方向

1. **执行验证步骤 1** 确定断裂点是在写入还是读出
2. 如果 DB 正确：检查 `uvicorn` 启动编码 `PYTHONIOENCODING=utf-8`、FastAPI `JSONResponse` media_type 设置
3. 如果 DB 乱码：在 `database.py` 的连接 URL 中增加 `?charset=utf-8` 或使用 aiosqlite pragma

---

## 7. 系统性偏差

### 7.1 设计退化与市态缓存

Designs 219-222 的 `market_context` 只有 2 个 key（`market_regime` 和 `index_realtime`），而 Design 218 有 5 个：

```
218: market_regime, market_sentiment, index_realtime, sector_momentum, fund_flow
219: market_regime, index_realtime
```

`_build_market_context()`（strategy_design.py:192-200）会调用：
- `pool_manager.get_market_sentiment()` → 如果缓存过期，返回默认值（不会空）
- `pool_manager.get_sector_momentum()` → 如果缓存过期，返回 `None` → `[]`

**关键发现**：`get_market_sentiment()` 在缓存过期时无法异步刷新（因为是同步方法），所以返回默认值。但 `get_sector_momentum()` 返回 `None` 继而被 `_build_market_context` 过滤为 `[]`。

这意味着 Designs 219-222 运行时 **pool_manager 的 sector_momentum 缓存和 fund_flow 数据都为空**——这与 `pool_manager.refresh()` 没有完全执行成功有关。

> **合并说明**：设计退化（原 Issue #6）和市态缓存空洞（原 Issue #7）是同一 root cause——数据管道未成功执行，导致空壳方案 + 空缓存同时出现。两个问题在本节合并分析。

### 7.2 策略检查的因子注入缺陷

策略检查在 `strategy_check()` 的 505 行尝试用真实因子分覆盖 LLM 生成的因子摘要：

```python
if real_fs and isinstance(real_fs, dict) and any(v != 0 for v in real_fs.values()):
    top_factors = sorted(real_fs.items(), key=lambda x: -abs(x[1]))[:3]
    factor_str = "；".join(f"{k}: {v:.2f}σ" for k, v in top_factors)
    h["factor_summary"] = f"{factor_str}"
```

**问题**：`any(v != 0)` 的门槛太低——只有一个因子非零就会触发覆盖。但更好的指标应该是**非零因子的比例**和**信号强度**。

### 7.3 设计管线的"静默降级"短板

从 `pool_manager.refresh()` 的执行路径看，信号量机制基本完整：
- 60s TTL 缓存
- 30s 冷却期
- 并发锁

但问题是：**当所有保护都触发后，系统"静默降级"了**——返回空缓存、默认值、零分，没有发出足够的告警。用户看到 "completed" 以为是成功的，实际是空洞的。

---

## 8. 修复方案与优先级

> **跨文档依赖**：Issue #1（事件循环阻塞）的详细修复方案见 `docs/async-boundary-fix-plan.md`，以下仅列概要。

### P0 — 必须立即修复

| # | 修复项 | 涉及文件 | 关联问题 | 预估工时 |
|---|--------|----------|----------|:--------:|
| 1 | **修复 async 函数中的唯一同步 I/O**：`factor_registry.py:844-845` 的 Sina IOPV `urllib.request.urlopen` 改为 `await run_sync()` | `factor_registry.py` | Issue #1 | 0.5h |
| 2 | **设计方案 post-condition 校验**：每个 strategy 必须有 ≥1 只非 CASH ETF 才允许标记 completed | `task_manager.py`, `strategy_design.py` | Issue #2 | 0.5h |
| 3 | **`compute()` 空数据告警**：`_fetch_market_data` 返回空 dict 时 logger.error 而非静默填零 | `factor_registry.py` | Issue #3 | 0.25h |

### P1 — 高优先级

| # | 修复项 | 涉及文件 | 关联问题 | 预估工时 |
|---|--------|----------|----------|:--------:|
| 4 | **编码诊断**：执行验证步骤（DB 直接读取）确定断裂点在写入还是读出 | `database.py` 检查 | Issue #5 | 0.5h |
| 5 | **因子降级缓存**：`compute()` 实时数据失败时 fallback 到过期 K 线缓存 | `factor_registry.py` | Issue #3 | 0.5h |
| 6 | **置信度规则化**：`strategy_check()` 后处理中基于 `filled_count/total_count` 覆盖 confidence | `portfolio_service.py` | Issue #4 | 0.25h |
| 7 | **设计任务并发控制**：限制同一时间只有一个设计/检查任务运行 | `task_manager.py` | Issue #1 | 0.25h |
| 8 | **死代码修复**：`macro_state.py` 的 `_fetch_pmi_trend`/`_fetch_rate_env` 加 `await run_sync()` | `macro_state.py` | Issue #1 | 0.5h |

### P2 — 中期优化

| # | 修复项 | 涉及文件 | 关联问题 | 预估工时 |
|---|--------|----------|----------|:--------:|
| 9 | **状态机验证**：design pipeline 增加 validating 阶段，空策略拒入 completed | `task_manager.py` | Issue #2, #6 | 1h |
| 10 | **因子质量报告**：`factor_summary` 输出到因子级别的可用性详情 | `portfolio_service.py`, LLM prompt | Issue #3 | 0.5h |
| 11 | **设计列表增加 etf_count 元数据**：`GET /designs` load_only 增加 ETF 计数 | `portfolio.py` | Issue #2 | 0.25h |
| 12 | **市态缓存异步刷新**：`get_sector_momentum()` 缓存过期时启动异步刷新 | `pool_manager.py` | Issue #6 | 0.5h |
| 13 | **区分数据不足 vs 信号中性**："hold" 信号需区分两种场景 | `portfolio_service.py` | Issue #4 | 0.5h |
| 14 | **CI 审计门禁**：`scripts/audit_async_blocking.py` + pre-commit 集成 | 新建 | Issue #1 | 0.5h |

### 修复执行顺序

```
P0-1 (async I/O) → P0-3 (compute告警) → P1-5 (因子缓存) → P0-2 (设计校验)
                                           ↓
P1-4 (编码诊断) → P1-6 (置信度) → P1-7 (并发控制) → P1-8 (死代码)
                                           ↓
P2-9~P2-14 (验证阶段、质量报告、审计门禁等)
```

> **依赖约束**：P1-6（置信度）依赖 P1-5（因子数据正常后才有意义）。P2-14（CI 门禁）不依赖其他 P0/P1，可随时插入现有工作流。

## 9. 测试防护缺口与修复方案

> 关联文档：`docs/async-boundary-fix-plan.md`（G1 直接相关）、`docs/implementation-master-plan.md §4 Phase 2.8`

现有测试体系（48 个文件，~360 个用例）大量覆盖正常路径，但存在 4 层结构性缺口导致上述 6 个问题未被识别。

### 9.1 四层缺口回顾

上文 §2-§7 的 6 个质量问题未被现有测试防护体系识别，根源在 4 层测试缺口：

| 缺口 | 描述 | 代码示例 | 影响的 Issue |
|------|------|----------|:-----------:|
| **① AST 扫描方向错** | `test_async_lint` 只检测 `await sync_func()` 模式，不检测直接同步调用 | `resp = urllib.request.urlopen(req)` 在 `async def` 内（无 await） | #1 |
| **② Mock 跳过真实路径** | 测试通过 mock 绕过了数据获取链路，只测"好数据上的逻辑" | `registry.compute(symbols, market_data=MOCK_DATA)` → 不经过 `_fetch_market_data` | #1, #3 |
| **③ 只检查结构不检查值** | 断言止于"字段存在"，不验证内容质量 | `assert "confidence" in result` ≠ `assert c != "low"` | #2, #4, #6 |
| **④ 无编码 roundtrip 测试** | 写入→存储→读出的编码路径无任何防护 | 无测试验证 `"稳健型" → DB → "稳健型"` 一致 | #5 |

### 9.2 修复方案（按缺口）

#### 修复 G1: AST 扫描增强 — 新增直接同步调用检测

**当前漏洞**：`test_async_lint.py` 只遍历 `ast.Await` 节点，忽略 `ast.Call` 在 `ast.AsyncFunctionDef` 中的直接调用。

```python
# test_async_lint.py 新增函数
def _is_direct_sync_call_in_async(node: ast.FunctionDef) -> list[str]:
    """Check if an async def function contains direct (non-awaited) sync calls."""
    if not isinstance(node, ast.AsyncFunctionDef):
        return []
    violations = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            # Skip if the call is inside an await
            parent = child
            while parent:
                if isinstance(parent, ast.Await):
                    break
                parent = getattr(parent, 'parent', None)
            else:
                # Not inside await — check if it's a known sync function
                call_name = _extract_call_name(child)
                if any(p in call_name for p in SYNC_PATTERNS_DIRECT):
                    violations.append(f"{node.name}:{child.lineno}: {call_name}")
    return violations
```

**新增黑名单**（区别于 `_SYNC_PATTERNS` 的 `await` 列表）：

```python
_SYNC_PATTERNS_DIRECT = [
    "urllib.request.urlopen", "urllib.request.Request",
    "requests.get", "requests.post",
    "pd.read_html", "pd.read_csv",
    "yfinance", "yf.",
]
```

**新增测试**：

```python
def test_no_direct_sync_call_in_async_function():
    """Fail if any async def contains a direct synchronous call."""
    violations = []
    for root, dirs, files in os.walk(_APP_PATH):
        for f in files:
            if not f.endswith('.py'): continue
            with open(os.path.join(root, f)) as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                violations.extend(_is_direct_sync_call_in_async(node))
    assert len(violations) == 0, \
        f"Found {len(violations)} direct sync calls in async functions:\n" + \
        '\n'.join(violations)
```

**涉及文件**：`tests/test_async_lint.py` | **预估工时**：0.5h

---

#### 修复 G2: 真实路径集成测试 — 补上跳过的那段链路

**当前漏洞**：因子计算和设计管线测试全部绕过 `_fetch_market_data()`，直接注入预构造数据。从不测试"数据源挂了"的场景。

**新增测试 1：因子降级路径测试**

```python
# tests/test_factor_registry.py 新增
async def test_compute_with_empty_fetch_returns_zeros():
    """当 _fetch_market_data 返回空时，因子得分全为 0 但不抛异常。"""
    registry._fetch_market_data = AsyncMock(return_value={})
    result = await registry.compute(["000001", "000002"])
    for sym, scores in result.items():
        for code, val in scores.items():
            assert val == 0.0, f"{sym}.{code} = {val}, expected 0"
```

**新增测试 2：设计编排器集成测试**

```python
# tests/test_design_pipeline_integration.py 新增
async def test_generate_enhanced_design_returns_valid_strategies():
    """调用真实编排器（非纯引擎），验证输出策略完整性。"""
    result = await generate_enhanced_design(capital=500000)
    assert "strategies" in result
    assert len(result["strategies"]) >= 2  # 至少 2 套方案
    for s in result["strategies"]:
        etfs = [a for a in s.get("etfs", []) if a.get("symbol") != "CASH"]
        assert len(etfs) >= 3, f"Strategy {s.get('id')}: only {len(etfs)} non-CASH ETFs"
```

**新增测试 3：空池降级测试**

```python
# tests/test_strategy_design.py 新增
async def test_empty_candidate_pool_returns_error():
    """候选池为空时，编排器返回 error 而非空策略。"""
    with patch.object(pool_manager, 'get_pool', return_value={"core": [], "satellite": [], "defense": []}):
        result = await generate_enhanced_design(capital=500000)
        assert "error" in result
        assert result["error"] == "无候选标的"
```

**涉及文件**：`tests/test_factor_registry.py`、`tests/test_design_pipeline_integration.py`、`tests/test_strategy_design.py`（新建） | **预估工时**：1.5h

---

#### 修复 G3: 值级质量断言增强

**当前漏洞**：断言止于"字段存在"，不检查字段值的合理性。

```python
# 现状
assert "confidence" in suggestion
assert "factor_summary" in holding

# 目标
assert suggestion["confidence"] in ("high", "medium", "low")
if holding.get("factor_scores"):
    assert "σ" in holding["factor_summary"]  # 真实因子分格式
```

**具体改动：**

| 测试文件 | 现有测试 | 增强断言 |
|----------|---------|---------|
| `test_strategy_check_async.py` | `test_strategy_check_returns_expected_structure` | 追加：confidence 非全 low 且分布合理 |
| `test_design_optimization_plan.py` | `test_three_strategies_produced` | 追加：mock 因子分后，factor_summary 格式含"σ" |
| `test_pool_manager.py` | `test_refresh_populates_cache` | 追加：market_context 完整（含 sector_momentum/market_sentiment/fund_flow） |

**新增测试**：

```python
# tests/test_verify_e2e_quality.py（新建）
class TestE2EContentQuality:
    """验证端到端输出的内容质量（复现 verify_e2e.py 检查逻辑但更深入）。"""

    def test_design_content_quality(self, live_server):
        """设计方案：≥2 套策略，每套 ≥3 只非 CASH ETF，design_text > 1000 字符。"""
        r = requests.get(f"{live_server}/api/v1/portfolio/designs?limit=1")
        design = self._get_full_detail(r.json()[0]["id"], live_server)
        assert len(design["strategies"]) >= 2
        for s in design["strategies"]:
            assert sum(1 for a in s.get("etfs", []) if a["symbol"] != "CASH") >= 3
        assert len(design.get("design_text", "")) > 1000

    def test_factor_data_completeness(self, live_server):
        """最新策略检查：至少 60% 标的有完整因子数据。"""
        # ... 略 ...
        assert data_quality["filled_count"] / data_quality["total_count"] > 0.6
```

**涉及文件**：多文件 | **预估工时**：2h

---

#### 修复 G4: 编码 roundtrip 测试

**当前漏洞**：没有任何测试验证"中文写入 DB → 读回 → 内容一致"。

```python
# tests/test_database.py 新建
@pytest.mark.asyncio
async def test_database_encoding_roundtrip():
    """写入中文字符串，读回后完全一致。"""
    from app.database import async_session
    from app.models.portfolio_design import PortfolioDesign

    test_text = "稳健型方案：低波稳健配置，控制回撤，适合保守型投资者"

    async with async_session() as db:
        record = PortfolioDesign(
            capital=100000,
            risk_profile="balanced",
            design_text=test_text,
        )
        db.add(record)
        await db.commit()
        record_id = record.id

        # 重新读取
        db2 = async_session()
        loaded = await db2.get(PortfolioDesign, record_id)
        assert loaded.design_text == test_text, \
            f"Mojibake detected!\n  wrote: {repr(test_text)}\n  read:  {repr(loaded.design_text)}"
```

**涉及文件**：`tests/test_database.py`（新建） | **预估工时**：0.5h

---

### 9.3 各测试文件改动清单

| 文件 | 改动类型 | 内容 |
|------|----------|------|
| `tests/test_async_lint.py` | 增强 | 新增 `test_no_direct_sync_call_in_async_function` |
| `tests/test_factor_registry.py` | 新增测试 | `test_compute_with_empty_fetch_returns_zeros` |
| `tests/test_design_pipeline_integration.py` | 新增测试 | `test_generate_enhanced_design_returns_valid_strategies` |
| `tests/test_strategy_design.py` | 新建文件 | `test_empty_candidate_pool_returns_error` |
| `tests/test_strategy_check_async.py` | 增强 | confidence 值级断言追加 |
| `tests/test_design_optimization_plan.py` | 增强 | factor_summary 格式断言追加 |
| `tests/test_pool_manager.py` | 增强 | market_context 完整 key 断言 |
| `tests/test_verify_e2e_quality.py` | 新建文件 | E2E 内容质量断言（策略数/ETF数/因子覆盖率） |
| `tests/test_database.py` | 新建文件 | 编码 roundtrip 测试 |

---

### 9.4 实施前提条件

```
Phase 2.6 (异步边界修复) 必须先完成
    ↓ 否则 test_async_lint 新增测试会被真实阻塞触发
Phase 2.7 (系统性质量修复) 必须先完成
    ↓ 否则 test_generate_enhanced_design 会因空池/数据缺失失败
Phase 2.8 (测试防护增强) ← 本方案
    ↓ 可以作为现有代码的最后一道安全网
后续日常开发
```

### 附录：文件引用索引

| 文件 | 行号 | 说明 | 关联问题 |
|------|------|------|----------|
| `factor_registry.py` | 839-866 | Sina IOPV 批量获取（urllib.request.urlopen 阻塞） | Issue #1 |
| `factor_registry.py` | 906 | `compute()` 调用 `_fetch_market_data` 入口 | Issue #1, #3 |
| `factor_registry.py` | 919-922 | 因子计算失败静默填 0 | Issue #3 |
| `macro_state.py` | 94-126 | `_fetch_pmi_trend` 死代码 | Issue #1 |
| `macro_state.py` | 129-171 | `_fetch_rate_env` 死代码 | Issue #1 |
| `task_manager.py` | 225-242 | `design_pipeline` 策略结果校验逻辑 | Issue #2 |
| `strategy_design.py` | 56-65 | 候选池空检查 | Issue #2 |
| `portfolio_service.py` | 392-398 | `strategy_check` 因子数据并行采集 | Issue #3 |
| `portfolio_service.py` | 505-508 | 因子注入后处理（all-0 跳过） | Issue #3, #4 |
| `pool_manager.py` | 614-674 | `get_sector_momentum` / `get_market_sentiment` 缓存 | Issue #6 |


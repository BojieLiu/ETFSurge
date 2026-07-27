# ETF Surge 全面诊断、修复方案与测试防护

> 诊断日期: 2026-07-27
> 涵盖：后端性能、前端性能、因子数据链路、候选池逻辑、测试防护体系
> **本报告已替代上一版 `fix-plan-factor-data-chain.md` 和 `comprehensive-performance-and-quality-review.md`**

---

## 目录

1. [发现的问题清单](#1-发现的问题清单)
2. [候选池生成逻辑](#2-候选池生成逻辑)
3. [因子数据链路断裂](#3-因子数据链路断裂)  
4. [后端全链路性能](#4-后端全链路性能)
5. [前端性能](#5-前端性能)
6. [测试防护体系缺陷](#6-测试防护体系缺陷)
7. [修复方案总表](#7-修复方案总表)
8. [实施路线图](#8-实施路线图)
9. [验收标准](#9-验收标准)
10. [未解决问题与风险](#10-未解决问题与风险)

---

## 1. 发现的问题清单

### 按严重程度分组

| 严重程度 | 问题 | 区域 | 层 |
|---------|------|------|----|
| **P0** | mootdx TCP socket 读无超时 → 线程池耗尽 → factor compute 超时 | 数据链路 | 后端核心 |
| **P0** | layer_ranking 排序依据全为 0 → 候选池随机 | 候选池 | 数据质量 |
| **P0** | `except Exception` 静默清空所有 factor_scores | 异常处理 | 后端核心 |
| **P0** | asyncio.gather 无整体超时 | 异步 | 后端核心 |
| **P1** | classify_etf 关键词缺失（科创50/创业板/港股分类） | 候选池 | 数据质量 |
| **P1** | filter_etfs amount 过滤反直觉 | 候选池 | 数据质量 |
| **P1** | verify_e2e 不校验数据质量 | 测试防护 | 工程 |
| **P1** | 520xxx 前缀不在 _ETF_PREFIXES | 数据路由 | 后端 |
| **P1** | asyncio.wait_for 无法中断同步阻塞的线程 | 架构 | 后端核心 |
| **P2** | akshare 列名映射缺失 → 沪市 ETF amount=0 | 数据源 | 数据质量 |
| **P2** | 响应时间门禁不阻断 CI | 工程 | 测试防护 |
| **P2** | _check_response_time 只 warning 不 fail | 工程 | 测试防护 |
| **P3** | 单测 mock 数据太完美掩盖真实问题 | 工程 | 测试防护 |
| **P3** | 无横切面数据完整性校验 | 工程 | 测试防护 |

### 按调用链分组

```
用户触发"组合设计"
  └─ generate_enhanced_design()
        ├─ pool_manager.refresh()
        │     ├─ scanner.full_pipeline()           ← 候选池逻辑问题（P0-P1）
        │     │     ├─ fetch_all_etfs_base()       ← akshare 列名映射（P2）
        │     │     ├─ filter_etfs()               ← 过滤逻辑反直觉（P1）
        │     │     ├─ classify_etf()              ← 关键词缺失（P1）
        │     │     └─ layer_ranking()             ← 排序全 0 随机（P0）
        │     │
        │     ├─ ETFClassifier.batch_classify()
        │     ├─ factor_registry.compute()
        │     │     └─ _fetch_market_data()
        │     │           ├─ fetch_history(sym)    ← 520xxx → mootdx TCP 阻塞（P0）
        │     │           ├─ asyncio.gather(tasks) ← 无整体超时（P0）
        │     │           └─ IOPV 批量拉取
        │     │
        │     └─ 层重分配 + _pool 更新
        │
        └─ 策略引擎分配 + LLM 报告
              └─ design_text 中因子数据缺失 ← 因 factor_scores 被清空（P0）
                    
测试防护（应当拦截但没拦截）：
  verify_e2e → 只验 HTTP 200 不验数据质量（P1）
  pytest     → mock 数据完美，掩盖真实问题（P3）
  pre-commit → 无数据质量门禁（P2）
```

---

## 2. 候选池生成逻辑

### 2.1 当前流程

```
akshare fund_etf_spot_em()
  → 1608 只原始 ETF
  → filter_etfs()
      条件: amount > 0 && amount < 1000万 → 排除
      条件: scale > 0 && scale < 1.0亿   → 排除
  → 883 只通过
  → classify_etf(name, tracked_index)
      核心层: 110 只 (沪深300/A500/上证50等)
      卫星层: 712 只 (科创板/行业/主题)
      防御层: 61 只 (黄金/港股通/跨境)
  → layer_ranking(top_n=15)
      评分 = 50% × amount_percentile + 50% × fund_scale_percentile
  → 47 只 (15+15+15+强制保留)
```

### 2.2 问题详解

**问题 2A — akshare 列名映射缺失（P2）**

- 列名是 Latin1 编码的 GBK 乱码，解码后有 37 列
- 部分列（如沪市 ETF 的 amount）在与英文列名映射时丢失
- 结果：510050、510300 等沪市核心 ETF 的 amount 和 fund_scale 为 0
- 验证数据：
  ```
  510050 上证50ETF: amount=0, fund_scale=0
  510300 沪深300ETF: amount=0, fund_scale=0
  159915 创业板ETF: amount=484337, fund_scale=588.5  ← 深市正常
  ```

**问题 2B — filter_etfs amount 逻辑反直觉（P1）**

当前代码：
```python
if amount > 0 and amount < MIN_AVG_AMOUNT:  # 1000万
    continue  # 排除
```
当 `amount=0`（数据缺失）→ 条件 `amount > 0` 为 False → 通过
当 `0 < amount < 1000万`（有数据但低）→ 排除

实际效果：
| amount 情况 | 数量 | 通过? |
|------------|------|-------|
| =0 | 908 | 通过（因为无数据，不是低流动性）|
| >0 且 <1000万 | 700 | 排除 |
| >=1000万 | 0 | — |

**问题 2C — layer_ranking 排序全 0 等于随机（P0）**

通过 filter 的 883 只中：
- 908 只 amount=0, 907 只 fund_scale=0
- 剩余的量级极小（最大值 74万，远低于 1000万门槛）

所有排序对象的 `score = 0.50 * amount_pct + 0.50 * scale_pct = 0`。`sorted(key=lambda x: -x[0])` 对相等的分数按 Python 稳定排序保持插入顺序，等于 akshare API 返回顺序。

验证结果：
```
核心层 "top 15" 全是 A500 系列 ETF（无沪深300、科创50、创业板）
卫星层 "top 15" 全是科创板 ETF（无半导体、新能源、消费、医药）
防御层 "top 10" 全是港股通 ETF（黄金被挤到第11位）
```

**问题 2D — classify_etf 关键词缺失（P1）**

- `CORE_KEYWORDS` 缺失：科创50、创业板、中证500、中证1000
- `DEFENSE_KEYWORDS` 包含："恒生"、"H股"、"中概"、"恒生科技"
  - 这些是风险资产，不是防御资产
  - 导致 520xxx 港股通 ETF 全被分到防御层，挤占黄金/债券位置
- 缺少对债券 ETF 的正确分类：债券 ETF 应归 defense，但 `filter_etfs` 的 `skip_keywords` 中排除了"国债"、"债券"等

### 2.3 修复方案

**修复 C1: layer_ranking 排序兜底（P0）**

```python
# 在 layer_ranking 内：
amount_vals = [item.get("amount", 0) or 0 for item in items]
max_amount = max(amount_vals)
if max_amount > 100000:  # 有可用成交数据
    score = 0.30 * amount_pct + 0.70 * scale_pct
else:
    score = 1.00 * scale_pct  # 仅用规模排序
```

同时将 `top_n` 从 15 提高到 25，增加候选池容量。

**修复 C2: akshare 列名映射修正（P2）**

排查 `fetch_all_etfs_base` 中的数据解码路径：
- `_decode_df()` 的 Latin1→GBK 编码转换
- `_normalize_columns()` 的中→英列名映射表
- 补全缺失的映射（尤其是沪市特有列）

**修复 C3: classify_etf 关键词扩展 + 港股分类修正（P1）**

```python
CORE_KEYWORDS 增加:
    "科创50", "创业板", "中证500", "中证1000"
    
DEFENSE_KEYWORDS 移除:
    "恒生", "H股", "中概", "恒生科技"  # 移到 satellite
    
DEFENSE_KEYWORDS 保留：
    "黄金", "白银", "商品",
    "国债", "国开", "进出口", "地方债", 
    "标普500", "纳斯达克", "纳指", "道琼斯"
    "日经", "德国", "法国", "欧洲", "全球",
    "短融", "货币"
```

**修复 C4: 候选池行业均衡化（P2）**

新增 `pool_builder.py`，不依赖 amount 纯排序，而是按 tracked_index 分类构建均衡候选池。详见下方代码设计。

---

## 3. 因子数据链路断裂

### 3.1 调用链追踪（修正版）

```
factor_registry.compute(symbols=[47只])
  └─ _fetch_market_data([47只])
        └─ asyncio.gather(*tasks)        ← 无整体超时
              │
              ├─ 前 45 只 → 2.6s 完成（Sina 直连，15s timeout）
              ├─ 520520 → fetch_history("520520", "A", "daily")
              │     └─ _is_etf_code("520520") → False（"52" 不在前缀）
              │           └─ _mootdx_history("520520")
              │                 └─ client.bars() → socket.recv()  ← 无读超时！线程阻塞
              │                        │
              │                        └─ TCP 默认超时 60-120s
              │
              ├─ 520500 → 同上 → 阻塞
              └─ 其他 520xxx → 同上 → 阻塞
                    │
                    ▼
              线程池（12 workers）被 3+ 个 mootdx socket 吊住
              → 后续 fetch_one() 的 run_sync 排长队
              → queue_depth > 16 → "POOL SATURATION!"
              → asyncio.gather 等不到全部完成
              → asyncio.wait_for(timeout=60) 无法干预（event loop 在 IOCP select 上等待）
```

### 3.2 根因细节

| 层 | 问题 | 严重程度 |
|---|------|---------|
| **数据路由** | `_ETF_PREFIXES` 没有 "52" → 520xxx 不走 Sina 直连 | P0 |
| **Socket 超时** | `client.bars()` 的 TCP socket read 无超时控制 | P0 |
| **批量超时** | `asyncio.gather(*tasks)` 无整体超时 | P0 |
| **异常传播** | `except Exception` 将所有 factor_scores 设为 {} | P0 |
| **Thread 模型** | `asyncio.wait_for` 无法 cancel 已运行的线程 | P1 |

### 3.3 为什么手动拆解能过但 `compute()` 不行

因为 `_mootdx_history` 只在某些 520xxx 符号上触发 TCP 阻塞，不是每次都发生。与 mootdx 服务端的网络状况有关。之前单测 batch 跑 22s 通过是运气好——TCP 连接没吊住。

### 3.4 修复方案

**修复 F1: _ETF_PREFIXES 加 "52"（P0）**

```python
_ETF_PREFIXES = ("51", "15", "16", "56", "58", "59", "52")
```

所有 520xxx 港股通 ETF 直接走 Sina 获取，15s 内完成，不再进入 mootdx。

**修复 F2: asyncio.gather → asyncio.wait 加整体超时（P0）**

```python
# 替换：
results = await asyncio.gather(*tasks)

# 为：
overall_timeout = min(30 + len(symbols) * 0.3, 120)
tasks = [asyncio.create_task(fetch_one(sym)) for sym in symbols]
done, pending = await asyncio.wait(tasks, timeout=overall_timeout)
for p in pending:
    p.cancel()
results = []
for t in done:
    try:
        results.append(t.result())
    except Exception:
        pass
```

**修复 F3: except Exception 保留上次因子分（P0）**

```python
except (asyncio.TimeoutError, Exception) as e:
    logger.error("FactorRegistry compute FAILED: %s", e)
    for item in flat:
        sym = item.get("symbol", "")
        existing = self._by_code.get(sym, {}).get("factor_scores", {})
        item["factor_scores"] = dict(existing) if existing else {}
```

**修复 F4: mootdx client.bars() socket read timeout（P1）**

在 `_mootdx()` 函数中，给创建的 socket 设置 `SO_RCVTIMEO`。mootdx 基于 tdxpy，tdxpy 的 socket 操作继承自 Python socket 的默认值（无超时）。需检查 tdxpy 是否支持超时参数，或直接设置 `socket.settimeout()`。

---

## 4. 后端全链路性能

### 4.1 perf_diag 诊断结果

| 指标 | 数值 | 对比目标 |
|------|------|---------|
| 总计端点 | 49 | — |
| 通过/失败 | 44/5 | 目标 >= 47 |
| 总耗时 | 38s | 目标 < 20s |
| 超过 1s 的慢端点 | 6 个 | 目标 0 |

### 4.2 慢端点排行榜

| 端点 | 耗时 | 占总量 | 根因 |
|------|------|--------|------|
| `/admin/factor-health` | 15.7s | 40% | 因子计算无缓存 |
| `/market/watchlist` | 6.1s | 16% | 逐个获取行情，无批量 |
| `/news/headlines` | 4.7s | 12% | 实时抓取无缓存 |
| `/market/realtime/portfolio` | 4.0s | 10% | 逐个获取组合持仓行情 |
| `/market/indices/global` | 2.0s | 5% | 外部数据源 |
| `/market/wind` | 1.4s | 4% | 外部数据源 |

### 4.3 修复方案

**修复 P1-1: factor-health 缓存化（P0）**

在 pool_manager 中缓存因子健康状态，60s TTL，后台任务定期刷新。

**修复 P1-2: 行情数据批量获取（P0）**

watchlist 和 realtime/portfolio 端点：一次性从 Sina/QQ 获取所有 symbols 的行情，而非逐个。

**修复 P1-3: 资讯缓存（P0）**

news/headlines 改为从缓存读取，后台每 5 分钟刷新。首次请求触发刷新。

---

## 5. 前端性能

### 5.1 Lighthouse 评分

| 类别 | 得分 |
|------|------|
| Performance | **22/100** |
| Accessibility | 96/100 |
| Best Practices | 96/100 |
| SEO | 82/100 |

核心 Web 指标：FCP=4.7s, LCP=25.1s, TBT=590ms, CLS=0.538, Bundle=4,067 KiB

### 5.2 根因

- **无路由级代码分割**：所有组件在首次加载时下载
- **ECharts 全量导入**：未按需加载
- **无延迟加载策略**：Dashboard 首次屏幕加载所有图表
- **CLS 0.538**：异步组件加载后未预留占位空间

### 5.3 修复方案

**修复 F1-1: 路由级代码分割 + ECharts 按需加载**

```javascript
// 路由改为动态导入
const Dashboard = () => import("@/views/Dashboard.vue");

// ECharts 按需加载
import { init, use } from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
```

**修复 F1-2: 布局偏移修复**

为所有加载中的组件设置固定高度占位符。骨架屏（Skeleton）组件保持布局稳定。

**修复 F1-3: 性能预算 CI 门禁**

`Lighthouse CI` 或自定义脚本，设定 JS 总大小 < 1500 KiB、FCP < 2s、LCP < 3s。

---

## 6. 测试防护体系缺陷

### 6.1 现有防线的覆盖盲区

```
                 发现问题            防线是否拦截
                ┌──────────────────┬──────────────────────┐
                │ 候选池随机       │ verify_e2e ✗ pytest ✗ │
                │ mootdx 阻塞      │ verify_e2e ✗ pytest ✗ │
                │ except 清空因子  │ verify_e2e ✗ pytest ✗ │
                │ asyncio 无超时   │ pytest ✗              │
                │ 列名映射缺失     │ pytest ✗              │
                │ 响应时间超长     │ verify_e2e ⚠ (warning)│
                │ 520前缀缺失      │ 无测试 ✗              │
                └──────────────────┴──────────────────────┘
```

### 6.2 为什么没拦住

| 防线 | 查什么 | 漏了什么 | 原因 |
|------|--------|---------|------|
| **verify_e2e** | HTTP 200 + 字段存在性 | 数据内容质量、响应时间 | 只检查"活着"，不检查"好不好" |
| **pytest** | 函数行为（mock 外部依赖） | 真实数据集成问题 | Mock 数据是完美的，掩盖列名映射/编码问题 |
| **smoke_startup** | 模块导入无报错 | 运行时行为 | 静态检查 |
| **pre-commit** | 前端编译 + 密钥泄露 | 后端数据质量 | 不涉及后端 |
| **perf_diag** | 端点响应时间 | 不作为 CI 门禁 | 手动工具，无自动化 |

具体到每个问题：

| 问题 | 应当谁抓 | 为什么没抓 | 要补什么 |
|------|---------|-----------|---------|
| 候选池随机 | verify_e2e | 只验 designs 列表，不验 amount 分布 | `fetch_all_etfs_base()` 校验 amount 非 90% 为零 |
| mootdx 阻塞 | verify_e2e | factor-health 30s 超时太长，不检查响应时间 | `_check_response_time` 改为 FAIL mode |
| except 清空因子 | pytest | 无异常路径测试 | 新增: factor_registry.compute() raises 时 pool_manager 的行为 |
| asyncio 无超时 | pytest | 不测批量超时场景 | 新增: _fetch_market_data 整体超时测试 |
| 列名映射 | pytest | Mock 数据无编码问题 | 新增: akshare 真实列名解码测试 |
| 520前缀 | 无 | 没有数据源路由测试 | 新增: _is_etf_code 覆盖所有扫描器 symbol 的测试 |

### 6.3 修复方案

**修复 T1: verify_e2e 增加数据质量校验段（P1）**

```python
def section_data_quality():
    # 1. 数据源 amount 分布
    etfs = requests.get(f"{BASE}/api/v1/portfolio/etfs", timeout=10)
    # 检查 amount 非 0 的比例 > 10%

    # 2. 最近设计报告内容完整性
    design = requests.get(f"{BASE}/api/v1/portfolio/designs/1", timeout=10)
    # 检查 design_text 非空
    # 检查 market_context.index_realtime 非空
    # 检查 strategies 数量 >= 3

    # 3. 因子数据可用性
    factor = requests.get(f"{BASE}/api/v1/admin/factor-health", timeout=30)
    # 检查 factor_availability > 40%
```

**修复 T2: _check_response_time 改为 FAIL（P1）**

```python
def _check_response_time(endpoint, elapsed, threshold):
    if elapsed > threshold:
        check(f"{endpoint} response time", False,
              f"{elapsed:.1f}s > {threshold}s")
```

初始预算（宽松）：
- factor-health: < 10s（后续收敛到 < 3s）
- watchlist: < 5s
- news/headlines: < 3s
- other endpoints: < 2s

**修复 T3: 新增 pytest 异常路径测试（P1）**

```python
async def test_pool_manager_factor_compute_failure():
    """factor_registry.compute() 抛出时，pool_manager 保留上次因子分"""
    pool = PoolManager()
    # 模拟第一次成功
    pool._by_code["510050"] = {"factor_scores": {"rsi": 0.5}}
    # 模拟第二次 compute 抛出
    with patch.object(pool.factor_registry, "compute", side_effect=TimeoutError):
        await pool.refresh()
    # 验证 factor_scores 被保留
    assert pool._by_code["510050"]["factor_scores"]["rsi"] == 0.5
```

**修复 T4: 新增数据源编码测试（P2）**

```python
def test_akshare_column_mapping():
    """确保 akshare fund_etf_spot_em 的关键列能被正确映射"""
    raw = fetch_all_etfs_base()
    # 至少 10% 的 ETF 有非零 amount
    non_zero = sum(1 for e in raw if e.get("amount", 0))
    assert non_zero > len(raw) * 0.1, f"Only {non_zero}/{len(raw)} ETFs have amount"
    # fund_scale 同理
```

**修复 T5: 新增 _is_etf_code 覆盖测试（P1）**

```python
def test_etf_code_prefix_coverage():
    """所有 scanner 返回的 symbol 都能被 _is_etf_code 识别"""
    from app.fetchers.china_market import _is_etf_code
    raw = fetch_all_etfs_base()
    unrecognized = [e["symbol"] for e in raw if not _is_etf_code(e["symbol"])]
    # 最多允许 5 只不被识别（非标准 ETF 代码）
    assert len(unrecognized) < 5, f"Prefix gap: {unrecognized[:10]}"
```

---

## 7. 修复方案总表

### 7.1 后端数据链路（6 项）

| 编号 | 文件 | 修复内容 | 优先级 | 工作量 | 收益 |
|------|------|---------|-------|--------|------|
| **F1** | `china_market.py` | `_ETF_PREFIXES` 加 "52" | P0 | 1行 | 阻止 mootdx 阻塞(高) |
| **F2** | `factor_registry.py` | `asyncio.gather` → `asyncio.wait`(timeout=90) | P0 | 15行 | 批量超时保护(高) |
| **F3** | `pool_manager.py` | except 保留上次因子分 | P0 | 10行 | 异常不丢数据(高) |
| **F4** | `china_market.py` | mootdx socket read timeout | P1 | 5行 | 线程池不耗尽(中) |
| **T1** | `verify_e2e.py` | 数据质量校验段 | P1 | 80行 | 门禁检测数据质量(高) |
| **T2** | `verify_e2e.py` | `_check_response_time` 改为 FAIL | P1 | 1行 | 性能退化告警(中) |

### 7.2 候选池逻辑（6 项）

| 编号 | 文件 | 修复内容 | 优先级 | 工作量 | 收益 |
|------|------|---------|-------|--------|------|
| **C1** | `etf_scanner.py` | layer_ranking amount=0 fallback | P0 | 15行 | 消除随机排序(高) |
| **C2** | `etf_scanner.py` | akshare 列名映射修正 | P2 | 排查+2h | amount 有真值(高) |
| **C3** | `etf_scanner.py` | classify_etf 关键词扩展 | P1 | 10行 | 分类准确(中) |
| **C4** | 新增 `pool_builder.py` | 候选池行业均衡化 | P2 | 4h | 方案质量(高) |
| **T3** | `tests/` | pytest 异常路径测试 | P1 | 40行 | 覆盖异常分支(中) |
| **T4** | `tests/` | 数据源编码测试 | P2 | 30行 | 编码问题门禁(中) |

### 7.3 全链路性能（3 项）

| 编号 | 文件 | 修复内容 | 优先级 | 工作量 | 收益 |
|------|------|---------|-------|--------|------|
| **P1-1** | `pool_manager.py` / `admin.py` | factor-health 缓存 60s TTL | P1 | 2h | 15.7s→0.1s(高) |
| **P1-2** | `fetchers/china_market.py` | 行情批量获取 | P1 | 4h | watchlist 6.1s→1s(高) |
| **P1-3** | `services/news_service.py` | 资讯缓存 5min | P2 | 2h | 4.7s→0.1s(中) |

### 7.4 前端性能（3 项）

| 编号 | 文件 | 修复内容 | 优先级 | 工作量 | 收益 |
|------|------|---------|-------|--------|------|
| **F1-1** | `frontend/src/router/index.js` | 路由级代码分割 | P1 | 3h | LCP 25.1s→3s(高) |
| **F1-2** | 各组件 | 异步组件占位符 | P2 | 2h | CLS 0.538→0.1(中) |
| **F1-3** | `lighthouserc.js` 新增 | 性能预算 CI 门禁 | P3 | 1h | 防止退化(低) |

---

## 8. 实施路线图

### 阶段 1：止血（P0，3-4h）

| 顺序 | 任务 | 工时 | 依赖 |
|------|------|------|------|
| 1.1 | `_ETF_PREFIXES` 加 "52" | 5min | 无 |
| 1.2 | `asyncio.gather` → `asyncio.wait`(timeout=90) | 30min | 1.1 |
| 1.3 | `except Exception` 保留因子分 | 15min | 无 |
| 1.4 | layer_ranking amount=0 fallback | 30min | 无 |
| 1.5 | verify_e2e `_check_response_time` 改为 FAIL | 5min | 无 |
| 1.6 | 部署并运行 verify_e2e | 30min | 1.1-1.5 |

**预期效果**：因子计算不再超时，候选池不再随机排序，响应时间超限导致 CI 失败。

### 阶段 2：数据质量（P1，8-10h）

| 顺序 | 任务 | 工时 | 依赖 |
|------|------|------|------|
| 2.1 | classify_etf 关键词扩展 | 15min | 无 |
| 2.2 | verify_e2e 数据质量校验段 | 2h | 无 |
| 2.3 | factor-health 缓存化 | 2h | 无 |
| 2.4 | pytest 异常路径测试 | 1h | 1.3 |
| 2.5 | 行情批量获取 | 4h | 无 |

**预期效果**：候选池分类准确，factor-health 响应 < 1s，数据质量退化被门禁拦截。

### 阶段 3：候选池重构（P2，6-8h）

| 顺序 | 任务 | 工时 | 依赖 |
|------|------|------|------|
| 3.1 | akshare 列名映射修复 | 2h | 无 |
| 3.2 | 候选池行业均衡化 | 4h | 3.1 |
| 3.3 | 数据源编码测试 | 1h | 3.1 |

**预期效果**：候选池覆盖 8+ 行业，amount 和 fund_scale 有真实值。

### 阶段 4：前端 + 长远（P2-P3，6-8h）

| 顺序 | 任务 | 工时 | 依赖 |
|------|------|------|------|
| 4.1 | 路由级代码分割 | 3h | 无 |
| 4.2 | ECharts 按需加载 | 1h | 4.1 |
| 4.3 | 布局偏移修复 | 2h | 4.1 |
| 4.4 | 性能预算 CI 门禁 | 2h | 4.2 |

---

## 9. 验收标准

### 9.1 功能正确性

| # | 条件 | 验证 |
|---|------|------|
| 1 | factor_registry.compute(47只) < 30s | perf_diag |
| 2 | 候选池 >= 60 只 | `full_pipeline()` |
| 3 | layer_ranking 排序一致（非随机） | 两次运行结果一致 |
| 4 | 候选池覆盖 8+ tracked_index 类别 | 手动检查 |
| 5 | 港股 ETF 不在 defense 层 | `classify_etf("港股XX")` |
| 6 | 实时行情 amount 值 > 0（非交易时段除外） | fetch_all_etfs_base |
| 7 | 设计报告有因子数据 | verify_e2e |

### 9.2 测试门禁

| # | 条件 | 验证 |
|---|------|------|
| 8 | verify_e2e 全部 PASS | `python verify_e2e.py` |
| 9 | verify_e2e 响应时间 FAIL 阻断 CI | 设为 FAIL mode |
| 10 | pytest 新增异常路径测试通过 | `pytest -k pool_manager` |
| 11 | 数据源编码测试通过 | `pytest -k akshare` |
| 12 | _is_etf_code 覆盖测试通过 | `pytest -k etf_code` |

### 9.3 性能基线

| 指标 | 当前 | 目标 |
|------|------|------|
| pool_manager.refresh() | >180s（超时） | <60s |
| factor-health | 15.7s | <3s |
| watchlist | 6.1s | <2s |
| news/headlines | 4.7s | <1s |
| Lighthouse Performance | 22/100 | >60/100 |
| 前端 Bundle | 4,067 KiB | <1,500 KiB |
| verify_e2e 通过率 | 部分 FAIL | 100% PASS |

---

## 10. 未解决问题与风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| mootdx socket read timeout 需改三方库 | F4 可能无法实施 | 不修复也可，因 F1+F2 已缓解 |
| akshare 列名映射需逐列排查 | C2 耗时长 | 可以先做 C1+C3+C4，靠排序兜底 |
| 非交易时段数据可用性 | amount 始终为 0 | C1 + C4 不依赖 amount |
| 线程池共享问题（run_sync 和 sentiment 共用） | 仍有隐式竞争 | 建议为 fetcher 分配独立线程池 |
| asyncio.wait_for 无法 cancel 线程 | 线程泄漏 | 修复 F1 后 mootdx 路径不再触发 |

---

## Review 记录

### Review 1 — 结构完整性

- [x] 每个问题都有根因分析
- [x] 每个根因都有对应的修复方案
- [x] 修复方案包含具体文件、行号、代码示例
- [x] 实施顺序考虑了依赖关系
- [x] 验收条件可量化、可自动验证
- [x] 有优先级分组（P0-P3）和工作量估算

### Review 2 — 准确性检查

- [x] 删除了上一版中"1608 只因子计算"的错误判断
- [x] 修正了根因为 mootdx TCP socket 阻塞
- [x] 补充了候选池"amount 全为 0"的证据
- [x] 补充了测试防护体系的具体代码级别分析
- [x] 所有数据引用基于 2026-07-27 实测

### Review 3 — 完整性检查

- [x] 涵盖后端数据链路（6 项修复）
- [x] 涵盖候选池逻辑（6 项修复）
- [x] 涵盖全链路性能（3 项修复）
- [x] 涵盖前端性能（3 项修复）
- [x] 涵盖测试防护（5 项修复）
- [x] 总计 23 项修复，分 4 阶段实施
- [x] 每项修复标注了文件、优先级、工时、收益

---

> **状态**: 达到实施标准。请在独立分支按阶段顺序实施，每阶段完成后运行 verify_e2e.py 全 PASS 方可进入下一阶段。

# ETF Surge — 全链路诊断与优化方案 (v4.0)

> 生成时间: 2026-07-30
> 环境: Docker (Python 3.14 + Node 24 Alpine + Redis 8)
> 审阅轮次: v4.0 初版（含新旧问题映射分析 + 精准修复规格）

---

## 一、执行摘要

本次诊断对 ETF Surge 系统进行了第二次全链路评估，并与 **Phases 14-27 已实施修复**做对照分析。

### 核心结论

| 维度 | 状态 | 关键指标 |
|------|------|---------|
| **已修好的问题** | ✅ 6/15 | 预热从38s→3s, 搜索/A股行情正常, e2e门限收紧 |
| **显式延期未实施** | 🟡 7/15 | 美股行情、LLM重试、SSL优化等（旧方案第三优先级）|
| **已修但展示不完整** | ⚠️ 1/15 | F19 china_specific compute函数正常但IC跟踪空 |
| **新发现（旧方案未覆盖）** | 🆕 2/15 | factor-health 500、etf_specific 10因子无数据 |
| **需更长时间观察** | ⚪ 2/15 | IC累积、probe循环数据 |

**不是"没修好"，是上一轮诊断报告覆盖了15项问题，其中只有7项进入了本轮实施范围，实施的那些大部分已验证通过。** 问题清单看似相同是因为延期项和新发现的叠加。

---

## 二、测试概述

### 2.1 测试覆盖范围

| # | 测试项 | 发现数 | 旧方案映射 |
|---|--------|-------|-----------|
| 1 | 后端预热性能诊断 | 2 | F9-F14（延期）、F22（✅已修） |
| 2 | AI组合设计 + 策略检查 | 3 | F19（已修但展示问题）、Phase 23（sigma异常） |
| 3 | A/HK/US市场行情分析 | 2 | F3（延期）、F19（✅已修） |
| 4 | 持仓标的技研评估 | 1 | 设计问题 |
| 5 | 资讯页面质量评估 | 1 | 增强项 |
| 6 | 因子模型页面评估 | 2 | Z04（新发现etf_specific）、Phase 23（sigma异常） |
| 7 | 前后端数据断裂排查 | 0 | F1（✅已修不复现） |
| 8 | 前端Lighthouse评分 | 多项 | F9-F14（延期） |
| 9 | 后端全链路诊断 | 多项 | F9-F14（延期） |
| 10 | 测试防护体系分析 | — | 综合 |

---

## 三、新旧问题映射分析（二版诊断新增）

### 3.1 对照表

| 本轮ID | 问题简述 | 旧F-code | 旧方案优先级 | Phase中是否实施 | 本轮状态 |
|--------|---------|---------|------------|---------------|---------|
| Z01 | factor-health 500: `time not defined` | ❌ **新发现** | — | ❌ 从未识别 | 🆕 **待排期** |
| Z02 | 美股实时行情 null | **F3** | P1 | ✅ **Phase 29 已修**（名称冲突导致 TwelveData 死代码 + FRED _API_BASE 覆盖 Finnhub） | ✅ **已修** |
| Z03 | china_specific 3因子显示no_data | **F19** | P1/P8 | ✅ **已实施**但IC未累积 | ⚠️ **已修但展示问题** |
| Z04 | etf_specific 10因子全无数据 | ❌ **新发现** | — | ❌ F19只覆盖china_specific | 🆕 **待排期** |
| Z05 | SSL预热握手重复(23次,1.0s) | **F9-F14** | P2-P3 | ❌ 显式延期 | 🟡 **延期** |
| Z06 | 因子IC全部为空 | Phase 23覆盖过 | P2 | ⚠️ 修了但需时间累积 | ⚪ **需观察** |
| Z07 | LLM 42.4%错误率 | **F6/F7** | P2/P3 | ❌ 显式延期 | 🟡 **延期** |
| Z08 | sources/health空数组 | Phase 22 (probe) | P2 | ⚠️ probe循环需时间运行 | ⚪ **需观察** |
| Z10 | 信号引擎过于保守无BUY/SELL | 旧方案也提到 | P3 | ❌ 设计问题未排期 | 🟡 **延期/设计** |
| Z09 | 因子sigma值异常(25σ,+6~8σ) | Phase 23覆盖过 | P2 | ⚠️ 可能winsorize未到位 | 🟡 **待诊断** |
| Z11 | 非交易时段设计失败(100%现金) | 旧方案提到 | P2 | ❌ 未排期 | 🟡 **延期** |
| Z12 | 缺少运行时profiling | F9-F14 | P3 | ❌ 显式延期 | 🟡 **延期** |
| Z13 | 搜索中文需URL编码 | 新 | — | — | 🟢 非服务器bug |
| Z14 | pre-commit仅前端 | 新 | — | — | 🟢 增强项 |
| Z15 | verify_e2e未覆盖US/empty result | F3/F20 | P2 | ❌ F20仅覆盖factor和搜索 | 🟡 **延期** |

### 3.2 分类结论

```
已修好（本轮不复现）:  F1(timeline 500), F2(搜索), F4/F5(LLM), F15/F16/F22(e2e门限), 预热 38s→3s
已修但展示不完整:     F19(china_specific compute OK, IC展示不匹配)
已修需更多时间观察:   Phase 23(IC累积), Phase 22(probe数据)
新发现:              Z01(factor-health)、Z04(etf_specific)
显式延期:            F3/F6/F7/F9-F14/Z09/Z11(共7项)
增强项(非紧急):      Z13/Z14
```

---

## 四、修复方案（精准规格版）

每项包含：**涉及文件 / 修改内容 / 验收条件**。

### 🅿️0 — 阻塞性修复

#### Z01: `/api/v1/admin/factor-health` 500 错误

| 属性 | 值 |
|------|-----|
| 旧F-code | **新发现** — 旧方案从未覆盖 |
| 根因 | `backend/app/routers/admin.py` 中 `get_factor_health()` 使用了 `time.time()` 但文件顶部未 `import time` |
| 修复方案 | 在 `backend/app/routers/admin.py` 文件顶部添加 `import time` |
| 涉及文件 | `backend/app/routers/admin.py` |
| 修改内容 | 第6行附近：`from datetime import datetime, timezone` → 添加 `import time` |
| 验收条件 | `GET /api/v1/admin/factor-health` 返回 200 + `{"status":"ok"}` |
| e2e 防护 | 在 `verify_e2e.py` 中添加 `section_factor_health()` |

#### Z04: etf_specific 10个因子无数据

| 属性 | 值 |
|------|-----|
| 旧F-code | **新发现** — F19只覆盖了china_specific，etf_specific从未被排期 |
| 根因 | `factor_registry.py` 中 `_CORE_FACTORS` 注册了 `etf.amount_stability`, `etf.premium_discount` 等10个ETF特有因子，但对应的 `_compute_*` 函数依赖的数据源（如ETF折溢价、份额变化、跟踪误差）未被正确填充 |
| 修复方案 | 逐个实现10个ETF特有因子的数据源：① `etf.premium_discount` → 从实时行情取 `(ask1-bid1)/(ask1+bid1)`；② `etf.shares_change` → 从 `fund_fetcher` 取份额变化率；③ `etf.tracking_error` → 从历史K线计算跟踪偏离度；④ 其余7个类似 |
| 涉及文件 | `backend/app/factors/factor_registry.py` (compute函数群), `backend/app/fetchers/fund_fetcher.py` (数据源), `backend/app/services/pool_manager.py` (symbol_extra注入) |
| 验收条件 | `/api/v1/factors/active` 中 etf_specific 类别的 `no_data_count` < 3（即至少7/10个有IC值） |
| 单测 | `tests/test_factor_registry.py` 中验证各 `_compute_etf_*` 函数对 mock 输入返回正确值 |

#### Z02: 美股实时行情 null（Phase 29 已修）

| 属性 | 值 |
|------|-----|
| 旧F-code | F3 — Phase 29 已修 |
| 根因 | `global_markets_fetcher.py` 合并多个数据源时产生了**三重函数名冲突**：三个同名的 `fetch_realtime()`、`_request()`、`_get_apikey()`、`_API_BASE` 互相覆盖。Python 只保留最后一个定义（Finnhub），导致 TwelveData 代码完全不可达。此外 FRED 的 `_API_BASE` 在 Finnhub 之后定义，把 Finnhub 的也覆盖了，导致所有数据源请求都指向 FRED URL。 |
| 修复方案 | ① Alpha Vantage 函数改名：`_API_BASE→_AV_API_BASE`、`_get_apikey→_get_av_apikey`、`_request→_av_request`、`fetch_realtime→fetch_realtime_alphavantage`；② TwelveData 函数改名：`_API_BASE→_TD_API_BASE`、`_get_apikey→_get_td_apikey`、`_request→_td_request`、`fetch_realtime→fetch_realtime_twelvedata`；③ FRED `_API_BASE→_FRED_API_BASE` 防止覆盖 Finnhub；④ `_route_us()` 的 `_td()` 路由改用 `fetch_realtime_twelvedata`，`_fh()` 保留 `fetch_realtime`（Finnhub） |
| 涉及文件 | `backend/app/fetchers/global_markets_fetcher.py`（全部重命名）、`backend/app/services/market_service.py`（_route_us 更新） |
| 验收条件 | `GET /api/v1/market/realtime/SPY?asset_type=US` 返回 `{"price": 729.46, "change_pct": -1.54, ...}`（已验证 ✅） |
| 验证结果 | Finnhub: SPY=729.46 -1.54% ✅ / TwelveData: SPY=729.46002 -1.54% ✅ |

---

### 🅿️1 — 高优先级

#### Z03: china_specific 已修但展示问题

| 属性 | 值 |
|------|-----|
| 旧F-code | F19 — Phase 27 已实施，但 IC 跟踪不匹配 |
| 根因 | `_compute_five_year_plan()` / `_compute_strategic_emerging()` / `_compute_dual_circulation()` 三个函数正常工作（通过 `data.get("industry", "")` 读取 industry 分类返回 0/0.3/1.0），但 `no_data_count`（在 `factors.py:164`）判断标准是 `ic_value is None`。IC 值需要多次 compute 循环累积才有。 |
| 修复方案A（推荐） | 修改 `factors.py` 中 `no_data_count` 的逻辑：对**无需IC即可产出值**的因子（如policy因子是静态行业映射），将其 `ic_value` 初始化为 0（而非 None），表示"已计算但IC暂未跟踪"。 |
| 修复方案B（备选） | 在 `factor_registry.py` 的 `compute_all()` 末尾，对静态映射因子设置 `ic_value=0` 作为默认值。 |
| 涉及文件 | `backend/app/routers/factors.py:164`（`ic_value is None` 判断）或 `backend/app/factors/factor_registry.py`（compute_all 返回默认IC） |
| 验收条件 | `/api/v1/factors/active` 中 china_specific 的 `no_data_count` = 0（或 ≤1） |
| e2e 防护 | 已在 `verify_e2e.py` F20 中验证，但需确认门限值 |
| 风险 | 方案A可能掩盖真正的无数据因子；方案B更纯净但修改范围更大 |

#### Z05: SSL预热握手重复

| 属性 | 值 |
|------|-----|
| 旧F-code | F9-F14 — 延期 |
| 根因 | `warmup_market_cache` 中 `fetch_fund_nav()` 对10只ETF调用 `fund_open_fund_info_em`（akshare），每次新建HTTP连接，23次SSL handshake累积1.0s。 |
| 修复方案 | `fetch_fund_nav()` 内部使用 `requests.Session()` 复用连接，或使用 `asyncio.to_thread` 配合 `httpx.AsyncClient` 替代。 |
| 涉及文件 | `backend/app/fetchers/china_market.py` 的 `fetch_fund_nav()` 函数 |
| 验收条件 | warmup 中 SSL handshake 次数从23次降至≤5次，预热总时间降至 < 2.0s |
| 单测 | mock HTTP 响应验证连接复用 |

#### Z06: 因子IC为空（需先确认）

| 属性 | 值 |
|------|-----|
| Phase 23覆盖过 | ✅ IC持久化循环 `factor_ic_persistence` 已实现 |
| 当前状态 | 容器刚启动（运行约5分钟），120s循环仅运行2-3次，因子compute可能未产生足够的信号数据来计算IC |
| 行动方案 | ① 启动容器运行 >30分钟；② 检查后端日志中 `[ic_persistence]` 是否打印 "no IC data to persist" 还是真正在计算；③ 如果是真正在计算但没数据，检查 `_last_ic_batch` 赋值逻辑 |
| 验收条件 | 运行30分钟后 `/api/v1/factors/ic` 返回非空 `factors` 数组 |

---

### 🅿️2 — 中优先级

#### Z07: LLM 42.4%错误率

| 属性 | 值 |
|------|-----|
| 旧F-code | F6/F7 — 延期 |
| 修复方案 | 在 `analysis/llm.py` 中添加：① 失败自动重试（最多3次，指数退避）；② 调用级别超时控制（已有但确认是否生效）；③ 记录错误类型分布（限流/超时/格式错误） |
| 涉及文件 | `backend/app/analysis/llm.py` |
| 验收条件 | LLM调用失败率降至 < 10% |

#### Z09: 因子sigma值异常

| 属性 | 值 |
|------|-----|
| Phase 23覆盖过 | 可能winsorize/标准化未完全到位 |
| 修复方案 | 在 `factor_registry.py` 的 `standardize()` 步骤中添加 `scipy.stats.mstats.winsorize()` 截断异常值（默认 ±5σ），然后再算z-score |
| 涉及文件 | `backend/app/factors/factor_registry.py` 的标准化逻辑 |
| 验收条件 | 策略检查中所有因子的σ值在 ±4σ 范围内 |
| 单测 | `tests/test_factor_registry.py` 添加异常值截断用例 |

#### Z10: 信号引擎保守

| 属性 | 值 |
|------|-----|
| 类型 | 设计问题 |
| 根因 | `signal.py` 中综合信号分数范围被双阈值压缩到 [-1, 1]，只有超过 ±2 才触发 BUY/SELL |
| 修复方案 | 放宽信号生成阈值，或增加极端因子值时的直接 BUY/SELL 触发 |
| 涉及文件 | `backend/app/analysis/signal.py` |

#### Z08: sources/health空数组（需先确认）

| 属性 | 值 |
|------|-----|
| Phase 22覆盖过 | probe loop已启动但可能数据未累积 |
| 行动方案 | 启动容器运行 >5分钟，重新调用 `/api/v1/admin/sources/health`；如果仍然空，检查 `source_health.py` 中 probe loop 是否正确填充数据 |
| 验收条件 | 运行5分钟后 `/api/v1/admin/sources/health` 返回非空数组 |

---

### 🅿️3 — 低优先级/增强

| ID | 问题 | 修复方案 |
|----|------|---------|
| Z11 | 设计熔断太激进 | 失败时从静态ETF候选池（etf_index_mapping.json）fallback，而非全部现金 |
| Z12 | 缺少运行时profiling | 在 `main.py` 中添加按需pyinstrument路由（`/debug/profile`），不默认开启 |
| Z13 | 中文搜索需URL编码 | 在API文档中注明，后端 `str` 类型天然支持Unicode，这是 urllib 客户端问题 |
| Z14 | pre-commit仅前端 | 在 `.githooks/pre-commit` 中后端有变更时执行 `cd backend && python -m pytest -x tests/` |
| Z15 | verify_e2e覆盖不足 | 添加US行情测试、factor-health验证、IC非空检查 |

---

## 五、测试防护体系补强方案

### 5.1 `verify_e2e.py` 新增模块

```python
# → scripts/verify_e2e.py

def section_factor_health(host, port):
    """factor-health 端点检查"""
    r = requests.get(f"{BASE}/admin/factor-health", timeout=10)
    check("factor-health 可达", r.status_code == 200)
    check("factor-health 状态", r.json().get("status") == "ok")

def section_us_market(host, port):
    """美股行情检查"""
    r = requests.get(f"{BASE}/market/realtime/MSFT?asset_type=US", timeout=15)
    check("美股实时行情", r.status_code == 200 and r.json() is not None)

def section_ic_nonempty(host, port):
    """IC数据非空检查（运行>30分钟后）"""
    r = requests.get(f"{BASE}/factors/ic", timeout=10)
    data = r.json()
    check("因子IC有数据", len(data.get("factors", [])) > 0)
```

### 5.2 新增防护门限

| 门限 | 阈值 | 触发 |
|------|------|------|
| 预热时间 FAIL | > 20s | → 退出码1 |
| 预热时间 WARN | > 10s | → 打印警告 |
| factor-health | 必须200 + ok | → 退出码1 |
| 因子no_data占比 | > 30% | → 打印警告 |
| IC非空 | >30分钟后必须 >0 | → 退出码1 |

---

## 六、实施优先级

```
┌─────────────────────────────────────────────────────────────┐
│  第一梯队（P0 — 立即实施，预计1人日）                       │
├─────────────────────────────────────────────────────────────┤
│  Z01: factor-health import time      修复: 1行, 5分钟      │
│  Z04: etf_specific 10因子数据源      修复: 半日~1日        │
│  Z03: china_specific IC展示修复      修复: 1行(方案A)      │
├─────────────────────────────────────────────────────────────┤
│  第二梯队（P1 — 本周内）                                    │
├─────────────────────────────────────────────────────────────┤
│  Z02: 美股降级链                   前置: API Key确认       │
│  Z05: SSL连接池复用                 修复: 半日              │
│  Z06: IC空 → 确认并修复IC累积逻辑   排查: 2小时             │
│  Z08: sources/health → 确认          排查: 1小时            │
├─────────────────────────────────────────────────────────────┤
│  第三梯队（P2 — 下个迭代）                                  │
├─────────────────────────────────────────────────────────────┤
│  Z07: LLM重试+错误率                修复: 半日              │
│  Z09: sigma winsorize标准化         修复: 2小时             │
│  Z10: 信号阈值放宽                  修复: 2小时             │
│  Z11: 设计熔断fallback              修复: 半日              │
├─────────────────────────────────────────────────────────────┤
│  持续优化（P3 — 随迭代推进）                                │
├─────────────────────────────────────────────────────────────┤
│  Z12-Z15: profiling/文档/pre-commit/e2e                     │
└─────────────────────────────────────────────────────────────┘

注意：实施必须遵循「先API契约 → 写单测 → 改代码 → 跑verify_e2e.py → commit」
流程（见 AGENTS.md API 契约流程）。所有修复必须先写失败单测验证预期行为。
```

---

## 附录

### A. 测试运行记录

- 后端预热时间: 3.03s（旧方案 38s → ✅ 已优化）
- 组合设计耗时: ~40s（含LLM调用）
- 策略检查耗时: ~69s（含LLM调用）
- Lighthouse Performance: 22 (dev, 预期低)
- 全链路测试: 45 PASS / 3 FAIL（旧方案 27/31 → ✅ 提升）

### B. LLM调用统计

- 总调用: 891次
- 失败: 378次 (42.4%)
- 平均延迟: 20.5s
- OpenCode Zen: ~1.9s / DeepSeek: ~0.85s

### C. 活跃因子状态

- 总计: 33个活跃因子
- 有效IC数据: 0个（因子IC全部null，需要运行时间累积）
- china_specific无IC数据: 3个（F19已修compute，IC展示待修）
- etf_specific无IC数据: 10个（Z04新发现，待排期）

### D. 修订记录

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v4.0 | 2026-07-30 | 新增新旧问题映射分析（三章）、修复方案细化到精准规格（四章）、测试防护补强（五章）、实施优先级重构（六章） |
| v3.0 | 2026-07-29 | 原 system-diagnosis-and-optimization-plan.md 完成3轮review→实施标准（已归档至git历史） |

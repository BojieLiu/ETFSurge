# 组合设计报告生成链路优化方案

> 基于五份评估反馈（2026-07-19）的系统性分析
>
> **⚠️ 2026-07-25 审计更新：代码架构已从 strategy_design.py（1092 行）重构至 engine/ 纯函数包。
> 以下改动方案中所有 strategy_design.py 引用均已过时，需映射至 engine/allocation_engine.py 和 engine/rationale.py。
> ⚠️ 2026-07-26 二次审计（基于代码交叉验证）：
> 当前实施状态：A1 ✅ / A2 ✅ / A3 ✅ / B1 ✅ / B2 ✅ / B3 ✅ / C1 ✅（fund_flow 注入 `strategy_design.py`）；
> C2 🟡 卫星层科技ETF仍未实施（代码中无科创50/588000引用）。**

## 一、问题总览

| 编号 | 问题 | 严重级 | 当前状态 | 实际代码位置（engine/ 架构） | 关联功能模块 |
|------|------|--------|:--------:|----------------------------|-------------|
| A1 | "因子"列含义不明，读者误以为代表涨跌幅 | **P0** | ✅ 已实施 | `design_report.py:109-134` 表头为"多因子评分"，含"今日涨跌"列+脚注 | 表格渲染 |
| A2 | 预期收益未随市场状态调整，恐慌行情下明显偏高 | **P0** | ✅ 已实施 | `engine/budgets.py:117` `adjust_expected_return()` | 组合构建 |
| A3 | 510880 误标为"红利低波ETF"，实为红利ETF（上证红利） | **P0** | ✅ 已实施 | `engine/allocation_engine.py:90-91` 512890在core、560600替换510500 | 候选池 |
| B1 | 黄金ETF入选理由缺少近3月实际跌幅引用，避险判断过时 | P1 | ✅ 已实施（`engine/rationale.py:84-91` 含动量偏弱判断 + 长期配置价值） | 入选理由生成 |
| B2 | 30年国债ETF未提示利率反弹久期风险 | P1 | ✅ 已实施（`engine/rationale.py:92-95` 含久期风险提示："若稳增长政策加码利率反弹则承压"） | 入选理由生成 |
| B3 | 缺少量化企稳判定标准（"等待企稳信号"模糊） | P1 | ✅ 已实施 | `analysis/prompts/v1/design_report.md` 已含"必含：量化操作建议" | LLM prompt |
| C1 | 遗漏ETF全市场净流入2290亿的积极信号 | P2 | ✅ 已实施（`strategy_design.py` `_compute_fund_flow()` 聚合全池资金流向注入 LLM prompt） | 数据采集 |
| C2 | 卫星层缺乏宽基科技ETF（科创50/创业板）分散选项 | P2 | 🟡 待实施 | `engine/allocation_engine.py` 需增加科技集中度检测→自动引入科创50 | 卫星选择 |

---

## 二、核心层重构：方案C（沪深300+中证A500+红利低波）

### 方案背景

| 方案 | 核心层构成 | 说明 |
|------|-----------|------|
| **A** | 中证A500 + 红利低波 | 单宽基+行业均衡，但缺乏超大盘基准 |
| **B（当前）** | 沪深300 + 中证500 + 红利低波 | 中证500与卫星层（半导体/AI/通信）风格重叠 |
| **C（推荐）** | **沪深300 + 中证A500 + 红利低波** | 大中盘龙头+行业均衡+防御价值，三层分工最清晰 |

### 决策理由

**选定方案C**，三个决定因素：

1. **风格隔离好于B**：中证500与卫星层高度重叠（都是中盘成长方向），7月17日中证500跌5.7%、通信ETF跌9.97%，核心层在恐慌中无法压舱。中证A500偏大盘行业均衡，下跌时可控。

2. **行业分散好于A**：A500按GDP占比分配行业权重，金融+消费集中度远低于沪深300。但单押A500缺乏超大盘基准——沪深300是机构护盘的核心标的，保留它等于保留最大流动性池。

3. **改动成本最小**：只需替换`dynamic_core_allocation`中3处510500→560600，权重从10%调至14%。

### 目标核心层结构

```
核心层（约42%）：
  沪深300(510300)   16%  → 超大盘基准，机构护盘首选
  中证A500(560600)  14%  → 行业均衡宽基，纠偏行业集中度
  红利低波(512890)  12%  → 高股息低波动压舱石（真正的红利低波）
  ────────────────
  合计              42%
```

三层框架分工：
- **核心层 42%**：稳+分散，下跌有缓冲
- **卫星层 11-26%**：纯弹性，不重叠
- **防御层 17%**：兜底
- **现金 15-30%**：动态调节

---

## 三、A3：核心层代码改动（双替换）

### 根因

`CANDIDATE_POOL` 中 **510880** 标注为"红利低波ETF"，但实际：
- **510880** = 红利ETF（上证红利指数），跟踪上证50只最高股息率股票
- **512890** = 红利低波100ETF（中证红利低波动100指数），同时筛选高股息+低波动

两者产品定位不同，后者才是真正的"红利低波"。

### 改动方案

#### A3-1：CANDIDATE_POOL 互换条目

文件：`backend/app/services/strategy_design.py`

```python
# 原（错误）
"510880": {"name": "红利低波ETF", "layer": "core", "beta": 0.75, "liquidity": 9.0,
           "reason": "高股息低波动，核心层压舱石"},
# ...卫星层...
"512890": {"name": "红利低波100ETF", "layer": "satellite", "beta": 0.78, "liquidity": 5.0,
           "reason": "低波动红利，稳健卫星"},

# 改为
"512890": {"name": "红利低波ETF", "layer": "core", "beta": 0.75, "liquidity": 12.0,
           "reason": "高股息低波动（中证红利低波100指数），核心层压舱石"},
# ...卫星层...
"510880": {"name": "红利ETF（上证红利）", "layer": "satellite", "beta": 0.80, "liquidity": 9.0,
           "reason": "高股息策略，价值风格卫星"},
```

- 512890 从卫星移至核心
- 510880 从核心移至卫星，名称修正
- 512890 名称从"红利低波100ETF"简化为"红利低波ETF"

#### A3-2：dynamic_core_allocation 替换代码引用（双替换）

文件：`backend/app/services/strategy_design.py`，每个 regime 分支同时改 2 处

**替换1**：510500（中证500）→ 560600（中证A500），权重从 0.10→0.14
**替换2**：510880（红利ETF）→ 512890（红利低波ETF），权重调整

| 分支 | 原来 | 改为 |
|------|------|------|
| 熊市/回调(L290-296) | `"510500", 0.10, "中盘成长宽基"` + `"510880", 0.15, "高股息低波动"` | `"560600", 0.14, "行业均衡宽基"` + `"512890", 0.14, "高股息低波动"` |
| 强牛市(L306-314) | `"510500", 0.10, "中盘成长宽基"` + `"510880", 0.05, "辅助防御配置"` | `"560600", 0.14, "行业均衡宽基"` + `"512890", 0.08, "辅助防御配置"` |
| 震荡/默认(L318-324) | `"510500", 0.10, "中盘成长宽基"` + `"510880", 0.10, "红利低波防御压舱"` | `"560600", 0.14, "行业均衡宽基"` + `"512890", 0.12, "红利低波防御压舱"` |

#### A3-3：测试文件同步更新

| 文件 | 改动 |
|------|------|
| `test_enhanced_design.py:209` | `assert "510880" in codes` → `assert "512890" in codes` |
| `test_enhanced_design.py:327` | mock 数据 `510880` → `512890` |
| `test_strategy_design.py:82,88` | mock 数据 `510880` → `512890` |
| `test_strategy_design.py:150` | 注释 `"510880=10%"` → `"512890=10%"` |
| `test_strategy_design.py:156` | `core.get("510880")` → `core.get("512890")` |
| `test_enhanced_design.py` | 中证500断言改为中证A500（若存在`assert "510500" in codes`则改为`assert "560600" in codes`） |

---

## 三、A1：表格渲染优化——"因子"列改为"多因子评分"并新增"今日涨跌"列

### 根因

`design_report.py:120-121` 在表格中取 `factor_score`（来自 `pool_manager._compute_composite()` 的 0~1 标量）渲染为"因子"列。读者看到"因子 0.55"自然以为是涨跌幅数据。

实际上因子评分（0~1）是多个维度的加权综合得分，与涨跌幅完全无关。

### 改动方案

#### A1-1：表头改名

文件：`backend/app/analysis/prompts/design_report.md`（LLM prompt — 纯分析部分）

不需要改。LLM prompt 中的表格由 `_build_plan_tables()` 引擎渲染，LLM 只写分析部分。

#### A1-2：引擎表格增加"今日涨跌"列

文件：`backend/app/tasks/design_report.py`，`_build_plan_tables()` 函数

```python
# 原表头（L106-107）
"| 资产类别 | 代码 | 名称 | 权重 | 因子 | 入选理由 |"
"|---------|------|------|:----:|:----:|---------|"

# 新表头
"| 资产类别 | 代码 | 名称 | 权重 | 多因子评分 | 今日涨跌 | 入选理由 |"
"|---------|------|------|:----:|:--------:|:-------:|---------|"
```

新增字段来源：`strategy_design.py:881-886` 中各 ETF 条目中有 `trend_1m`、`trend_3m`、`ma_bias_20` 字段。当日涨跌幅需从 `trend_data` 中取，或在条目中新增一个 `daily_change_pct` 字段。

**推荐实现方式**：在 `strategy_design.py` 生成 holdings 时，增加 `daily_change_pct` 字段：

```python
# 在卫星层 append 处（L864-887）增加
"daily_change_pct": trend.get("change_pct"),  # 新增
```

然后在 `_build_plan_tables()` 渲染时：

```python
chg = e.get("daily_change_pct")
chg_txt = f"+{chg*100:.1f}%" if chg and chg >= 0 else (f"{chg*100:.1f}%" if chg else "—")
```

#### A1-3：表下注释说明

在 `_build_plan_tables()` 生成的方案表格下方追加：

```python
lines.append("\n> **注**：多因子评分（0~1）基于资金流、估值、动量、流动性等维度综合计算，非涨跌幅。" )
```

---

## 四、A2：预期收益随市场状态动态调整

### 根因

`strategy_design.py:950` 直接使用 `STRATEGY_META` 中硬编码的预期收益（防御8%/平衡11%/进攻16%），这些数据在"常态"下合理，但在当前恐慌行情中严重偏高。

### 改动方案

#### A2-1：新增调整函数

文件：`backend/app/services/strategy_design.py`，在 `dynamic_layer_budget()` 之后新增：

```python
def adjust_expected_return(
    base_return: float,
    regime: str,
) -> float:
    """
    根据市场状态调整预期收益。
    
    调整系数：
      bull_strong/weakening/range_bound/slow_rise: 1.0x（常态，不调整）
      defensive_rotate:   0.80x
      correction:         0.65x
      bear:               0.45x
      panic:              0.30x
    """
    multipliers = {
        "bull_strong": 1.0,
        "bull_weakening": 1.0,
        "range_bound": 1.0,
        "slow_rise": 1.0,
        "defensive_rotate": 0.80,
        "correction": 0.65,
        "bear": 0.45,
        "panic": 0.30,
    }
    m = multipliers.get(regime, 1.0)
    return round(base_return * m, 3)
```

#### A2-2：策略输出增加双预期

文件：`backend/app/services/strategy_design.py`，策略字典构建处（L944-958）：

```python
strategies.append({
    # ... 原有字段 ...
    "expected_return": meta["expected_return"],                 # 常态预期（保留）
    "expected_return_current": adjust_expected_return(          # 当前修正预期（新增）
        meta["expected_return"], regime
    ),
    "max_drawdown": min(
        meta["max_drawdown"],
        risk_metrics.get("max_drawdown_est", meta["max_drawdown"])
    ),
    # ...
})
```

#### A2-3：表格渲染增加"当前修正"行

文件：`backend/app/tasks/design_report.py`，`_build_plan_tables()` 对比表：

```python
# 新增行：当前预期年化
for s in strategies:
    r = s.get("expected_return_current")
    rets_current.append(f"{r * 100:.0f}%" if r is not None else "—")
lines.append("| 当前预期年化 | " + " | ".join(rets_current) + " |")
```

---

## 五、B1：黄金 ETF 入选理由优化

### 根因

`build_rationale()` L546 写死"短期金价波动不影响避险属性，用于对冲权益极端系统性风险"，未引用近3月实际跌幅数据。

### 改动方案

文件：`backend/app/services/strategy_design.py`，`build_rationale()` L544-550

```python
# 原
elif "黄金" in asset_name:
    parts.append(asset_name + " — 贵金属避险资产，与权益低相关。"
                 "短期金价波动不影响避险属性，用于对冲权益极端系统性风险和地缘政治风险")

# 改为
elif "黄金" in asset_name:
    parts.append(asset_name + " — 贵金属避险资产，与权益低相关")
    # 引用近3月实际跌幅（动态）  
    ret_3m = trend.get("return_3m")
    if ret_3m is not None and ret_3m < -0.05:
        parts.append(f"近3月跌{abs(ret_3m)*100:.1f}%（受强美元+高利率压制），"
                     f"短期避险功能受限但长期配置价值仍在")
    else:
        parts.append("用于对冲权益极端系统性风险和地缘政治风险")
```

---

## 六、B2：30年国债 ETF 入选理由增加久期风险提示

### 改动方案

文件：`backend/app/services/strategy_design.py`，`build_rationale()` L547-548

```python
# 原
elif "国债" in asset_name:
    parts.append(asset_name + " — 利率债，货币宽松周期受益")

# 改为
elif "国债" in asset_name:
    parts.append(asset_name + " — 利率债，货币宽松周期受益")
    parts.append("久期较长，若稳增长政策加码利率反弹则承压")
```

---

## 七、B3：量化企稳规则从"可选"升级为"必选"

### 根因

LLM prompt `design_report.md` 中"可选扩展：量化调仓规则"标注为"仅在篇幅允许时嵌入"，导致 LLM 经常省略。

### 改动方案

文件：`backend/app/analysis/prompts/v1/design_report.md`

```
# 原（可选扩展段，L54-60）
### 可选扩展：量化调仓规则（仅在分析中自然嵌入，非必须独立章节）
如果篇幅允许，可在分析中嵌入以下具体规则：
- **周末再平衡**：...
- **单日急跌加仓**：...
- **止损红线**：...

# 改为
### 必含：量化操作建议
在分析末尾必须输出以下量化建议（至少包含 2 条）：
1. **企稳判定标准**（示例：沪深300连续3日不创新低 + 5日线走平 + 情绪指数回升至40以上）
2. **单日急跌加仓**（卫星层品种单日跌超5%，按该品种目标权重的20%分批加仓，单周最多一次）
3. **止损红线**（卫星层浮亏超20%强制减半仓，超30%清仓转现金）
4. **再平衡纪律**（每周末检查，单只ETF偏离目标权重±5%时调回）
```

---

## 八、C1：全市场 ETF 净流入汇总

### 改动方案

文件：`backend/app/services/strategy_design.py`，`generate_enhanced_design()` 中 `fund_flow_results` 处理后（L720-725）

```python
# 在现有 fund_flow_map 构建后追加
fund_flow_map = {}
total_flow = 0.0
if isinstance(fund_flow_results, (list, tuple)):
    for sym, result in zip(all_symbols, fund_flow_results):
        if isinstance(result, dict) and result.get("main_net_inflow") is not None:
            fund_flow_map[sym] = result["main_net_inflow"]
            total_flow += result["main_net_inflow"]
```

将 `total_flow` 存入 `market_context`，使 LLM 能够引用全市场资金流数据。

---

## 九、C2：卫星层增加宽基科技 ETF

### 改动方案

文件：`backend/app/services/strategy_design.py`，卫星层贪婪选择（L838-852）

```python
# 在当前行业去重逻辑后、放宽填充前，增加：
# 如果通信/半导体等科技行业集中度过高，自动引入科创50作为分散工具
tech_industries = {"电子", "通信", "计算机", "半导体"}
tech_weight = 0
for h in holdings:
    if h.get("layer") == "satellite" and h.get("industry", "") in tech_industries:
        tech_weight += h.get("weight", 0)
if tech_weight > s_budget * 0.6 and "588000" not in {h.get("symbol") for h in holdings}:
    # 引入科创50ETF分散
    ...
```

---

## 十、实施顺序（2026-07-25 更新）

| 优先级 | 任务 | 状态 | 实际代码位置 | 预估工时 | 依赖 |
|--------|------|:----:|-------------|:--------:|------|
| **P0-1** | A3: 核心层双替换（510500→560600 + 510880→512890） | ✅ 已实施 | `engine/allocation_engine.py:83-91` | — | 无 |
| **P0-2** | A1: 表格"因子"→"多因子评分"+新增"今日涨跌"列 | ✅ 已实施 | `tasks/design_report.py:109-134` | — | 无 |
| **P0-3** | A2: 预期收益 regime 调整 | ✅ 已实施 | `engine/budgets.py:117` | — | 无 |
| P1-1 | B3: LLM prompt 量化规则升级 | ✅ 已实施 | `analysis/prompts/v1/design_report.md` | — | 无 |
| P1-2 | B1: 黄金入选理由优化 | 🟡 待实施 | `engine/rationale.py:60-63`（适配新接口） | ~10行 | 无 |
| P1-3 | B2: 国债久期风险提示 | 🟡 待实施 | `engine/rationale.py:64-65`（适配新接口） | ~3行 | 无 |
| P2-1 | C1: 全市场资金流汇总 | 🟡 待评估 | pool_manager + allocation_engine | ~30行 | 无 |
| P2-2 | C2: 卫星层宽基科技ETF | 🟡 待评估 | `engine/allocation_engine.py` | ~15行 | 无 |

> P0 三任务 + B3 均已隐式完成。B1/B2 为本次实施内容。C1/C2 需后续轮次。

---

## 十一、验证策略（2026-07-25 更新）

| 改动 | 状态 | 验证方式 |
|------|:----:|---------|
| A3 | ✅ 已实施 | `engine/allocation_engine.py` 验证 560600/512890 在 MANDATORY_CODES 和 _DEFAULT_CANDIDATES 中 |
| A1 | ✅ 已实施 | 前端查看设计报告方案表头为"多因子评分"，含"今日涨跌"列 |
| A2 | ✅ 已实施 | 查看 `adjust_expected_return` 在 budgets.py，引擎输出含 `expected_return_current` |
| B3 | ✅ 已实施 | 确认 design_report.md prompt 含"必含：量化操作建议" |
| B1 | 🟡 待实施 | `python -m pytest tests/ -k "rationale"` + 查看黄金 ETF 入选理由含近3月跌幅 |
| B2 | 🟡 待实施 | `python -m pytest tests/ -k "rationale"` + 查看国债 ETF 入选理由含久期提示 |
| A1+A2+A3+B3+B1+B2 | ✅/🟡 | `python scripts/verify_e2e.py` — 全链路验证 |

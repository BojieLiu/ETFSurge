# 策略检查分析优化方案

> 版本: v1.0  
> 日期: 2026-07-19  
> 状态: 设计阶段

---

## 1. 现状分析

### 1.1 当前链路

```
前端 DashboardAiTools.vue
  └─ [策略检查分析] 按钮
       └─ enterStrategyMode() → activeCoreFeature = 'strategy'
            └─ 功能卡片（说明三项能力）
                 └─ checkStrategy()
                      └─ POST /api/v1/portfolio/strategy-check
                           └─ strategy_check(db, total_capital, design_data)
                                ├── list_etfs() / design_data → 获取持仓
                                ├── build_price_map() → 实时行情
                                ├── for each ETF:
                                │    get_history() → compute_all_indicators() → generate_signal()
                                │    # 仅 MA5/10/20/60, MACD, RSI, KDJ, Bollinger
                                ├── get_indices() + get_commodities()
                                ├── fetch_news_headlines() + fetch_macro_news()
                                └── generate_strategy_suggestions()
                                     └── 简单 prompt → LLM → JSON({strategies: [...]})
```

### 1.2 发现的问题

| 问题 | 严重度 | 说明 |
|------|--------|------|
| **前端结果无展示** | P0 | `strategyResult` 存入 ref 后模板无渲染区，用户只看到 toast |
| **未接入因子模型** | P0 | factor_registry 128 个因子完全未用，只用 5 个技术指标 |
| **未复用 calculate_allocation** | P1 | 自制重复逻辑，缺 supported_index 映射和 fundamental 数据 |
| **未接入市场状态判定** | P1 | 无 regime 检测，LLM 缺乏关键上下文 |
| **LLM prompt 过简** | P2 | 无结构化 prompt，无数据引用，输出格式自由 |
| **未异步化** | P3 | 同步阻塞，不支持 WS 推送进度 |

### 1.3 与已有基础设施的差距

```
项目已有基础设施                    strategy_check 使用情况
─────────────────────────────────────────────────────────────
factor_registry + 128因子              ❌ 未使用
ic_tracker (IC/ICIR 验证)             ❌ 未使用
detect_market_regime()                 ❌ 未使用
detect_macro_regime()                  ❌ 未使用
calculate_allocation()                 ❌ 未使用（自制重复逻辑）
calculate_daily_pnl()                  ❌ 未使用
DesignTaskManager + WS 推送            ❌ 未使用（同步阻塞）
build_rationale() 数据驱动理由生成      ❌ 未使用
PoolManager (composite_score)          ❌ 未使用
```

---

## 2. 目标架构

### 2.1 升级后链路

```
前端:
  [策略检查分析] 按钮
       └─ 功能卡片 → [开始检查]
            └─ POST /api/v1/portfolio/strategy-check
                 │
                 └─ strategy_check_v2()
                      │
                      ├── ① 持仓获取
                      │    └─ _resolve_etfs(db, design_data)
                      │
                      ├── ② 复用 calculate_allocation()
                      │    └─ 附带 tracked_index 映射 + fundamental 数据
                      │
                      ├── ③ 并行数据采集 (asyncio.gather)
                      │    ├── _compute_indicators(symbols)
                      │    │    └─ get_history() → compute_all_indicators() + generate_signal()
                      │    ├── factor_registry.compute(symbols)
                      │    │    └─ 因子评分: momentum/volatility/liquidity/valuation/ma_trend
                      │    ├── _detect_regime(symbols)
                      │    │    ├── compute_etf_trends() → 多周期收益率/乖离率
                      │    │    ├── fetch_index_realtime()
                      │    │    └── detect_market_regime() → bull_strong/range_bound/bear...
                      │    └── get_indices() + get_commodities() + fetch_news()
                      │
                      ├── ④ 合并 factor_breakdowns
                      │    └─ 每只持仓: {技术指标, 技术信号, 因子评分, 权重偏离度}
                      │
                      ├── ⑤ generate_strategy_check_report()
                      │    ├── 专用 prompt: strategy_check.md
                      │    ├── 强制 JSON + 结构化字段
                      │    └── AgentRuntime("strategy_check").run_json()
                      │
                      └── ⑥ return {
                              summary,              # 综述
                              suggestions,          # 操作建议（可 apply-strategy）
                              holdings_analysis,    # 逐只持仓分析
                              risk_warnings,        # 风险预警
                              market_regime,        # 市场状态
                          }

前端渲染:
  strategyResult →
      ├── 市场状态徽标
      ├── 综述段落
      ├── 持仓分析表（含因子分/技术信号/偏离度）
      ├── 风险预警列表（按 severity 着色）
      └── 操作建议卡片（weight % → %, 置信度, 一键应用）
```

### 2.2 数据流对比

```
当前:
  5 个指标 ─→ LLM ─→ {strategies: [...]}
  ↑
  持仓行情 + 指数 + 新闻

升级后:
  5 个指标 + 因子评分 + regime + 完整 allocation ─→ LLM ─→ {
    summary,
    suggestions: [{action, symbol, name, current_weight, suggested_weight, reason, confidence}],
    holdings_analysis: [{symbol, name, factor_summary, tech_signal, risk_flag}],
    risk_warnings: [{type, severity, description, affected_symbols}],
    market_regime
  }
```

---

## 3. 具体改动

### 3.1 Phase 1: 后端数据增强

#### 文件: `backend/app/services/portfolio_service.py`

**改动内容：**
1. 新增导入: `factor_registry`, `compute_etf_trends`, `detect_market_regime`, `fetch_index_realtime`
2. 重构 `strategy_check()` → `strategy_check_v2()`:
   - 复用 `calculate_allocation()` 替代手写持仓逻辑
   - 追加 `asyncio.gather` 并行采集因子分 + regime + 技术指标
   - 合并 `factor_breakdowns` 结构
3. 拆出辅助函数:
   - `_resolve_etfs()` — 从 DB 或 design_data 获取持仓
   - `_compute_indicators()` — 并行计算技术指标+信号
   - `_detect_regime()` — 并行获取趋势+指数+判定市场状态

```python
# 新增导入
from ..factors.factor_registry import registry as factor_registry
from .market_trends import compute_etf_trends, detect_market_regime
from ..fetchers.china_market import fetch_index_realtime

async def strategy_check_v2(db, total_capital, design_data=None):
    """v2: 因子评分 + regime 感知 + 复用 calculate_allocation"""

    etfs = await _resolve_etfs(db, design_data)
    if not etfs:
        return {"summary": "组合为空", "suggestions": []}

    # 复用组合计算引擎
    allocation_data = await calculate_allocation(db, total_capital, "on_exchange", etfs)
    market_data = allocation_data["allocations"]
    symbols = [a["symbol"] for a in market_data if a["symbol"] != "CASH"]

    # 并行采集
    indicators, factor_scores, (trends, index_realtime, regime) = await asyncio.gather(
        _compute_indicators(symbols),
        factor_registry.compute(symbols),
        _detect_regime(symbols),
        return_exceptions=True,
    )

    indicators = indicators if isinstance(indicators, dict) else {}
    factor_scores = factor_scores if isinstance(factor_scores, dict) else {}
    regime = regime if isinstance(regime, str) else "range_bound"

    # 合并因子断点
    factor_breakdowns = {}
    for sym in symbols:
        factor_breakdowns[sym] = {
            "technical_indicators": indicators.get(sym, {}),
            "technical_signal": indicators.get(sym, {}).get("signal", {}),
            "factor_scores": factor_scores.get(sym, {}),
            "weight_drift": _calc_drift(allocation_data, sym),
        }

    # 带 structured prompt 的 LLM 分析
    result = await generate_strategy_check_report(
        market_data=market_data,
        factor_breakdowns=factor_breakdowns,
        regime=regime,
    )

    return {
        "summary": result.get("summary", ""),
        "suggestions": result.get("suggestions", []),
        "holdings_analysis": result.get("holdings_analysis", []),
        "risk_warnings": result.get("risk_warnings", []),
        "market_regime": regime,
        "raw_llm": str(result),
    }
```

状态迁移: `strategy_check()` 函数可以保留（更名为 `strategy_check_v1` 作为 fallback），路由层指向 v2。

### 3.2 Phase 1: 辅助函数

```python
async def _resolve_etfs(db, design_data):
    """从 DB 或 design_data 获取持仓列表。"""
    use_design = False
    if design_data and design_data.get("plans"):
        plan = design_data["plans"][0] if design_data["plans"] else None
        if plan and plan.get("allocations"):
            etfs = []
            for alloc in plan["allocations"]:
                etfs.append({
                    "symbol": alloc.get("symbol"),
                    "name": alloc.get("name", alloc.get("symbol")),
                    "short_name": alloc.get("short_name", alloc.get("symbol")),
                    "asset_type": "ETF",
                    "portfolio_type": "on_exchange",
                    "target_weight": alloc.get("target_weight", 0),
                })
            use_design = True
    if not use_design:
        etfs = await list_etfs(db)
    return etfs


async def _compute_indicators(symbols):
    """并行计算每只持仓的技术指标 + 信号。"""
    results = {}
    hist_data = await asyncio.gather(
        *[get_history(sym, "A") for sym in symbols],
        return_exceptions=True,
    )
    for sym, hist in zip(symbols, hist_data):
        if isinstance(hist, list) and hist:
            ind = compute_all_indicators(hist)
            sig = generate_signal(ind)
            ind["signal"] = sig
            results[sym] = ind
    return results


async def _detect_regime(symbols):
    """并行获取 trend + index → detect_market_regime。"""
    trends, index_realtime = await asyncio.gather(
        compute_etf_trends(symbols, ("5d", "1m", "3m")),
        asyncio.to_thread(fetch_index_realtime),
        return_exceptions=True,
    )
    trends = trends if isinstance(trends, dict) else {}
    index_realtime = index_realtime if isinstance(index_realtime, list) else []

    regime = detect_market_regime(
        trends=trends,
        broad_index_code="510300",
        index_realtime=index_realtime,
    )
    return trends, index_realtime, regime


def _calc_drift(allocation_data, symbol):
    """计算单只 ETF 的权重偏离度。"""
    for a in allocation_data.get("allocations", allocation_data if isinstance(allocation_data, list) else []):
        if isinstance(a, dict) and a.get("symbol") == symbol:
            target = a.get("target_weight", 0)
            current = a.get("current_weight", 0) or a.get("weight", 0)
            return {
                "target_weight": target,
                "current_weight": current,
                "drift": round(current - target, 4),
                "drift_pct": round((current - target) * 100, 2),
            }
    return None
```

### 3.3 Phase 2: 新增 LLM prompt 文件

#### 文件: `backend/app/analysis/prompts/v1/strategy_check.md`

```markdown
# 角色设定

你是一位 ETF 组合策略分析师。基于当前持仓数据和市场状态，输出结构化分析报告。

# 输入数据

1. 持仓明细（含每只标的的当前权重、目标权重、偏离度、技术信号、因子评分）
2. 市场状态（regime）
3. 指数行情 + 资讯

# 输出要求

严格 JSON，不要额外文字：

```json
{
  "summary": "总体分析结论（2-3句话，直接给出判断，不要开场白）",
  "suggestions": [
    {
      "action": "increase|decrease|hold|add|remove",
      "symbol": "510300",
      "name": "沪深300ETF",
      "current_weight": 0.25,
      "suggested_weight": 0.30,
      "reason": "因子评分排名前3，动量持续，建议超配",
      "confidence": "high|medium|low"
    }
  ],
  "holdings_analysis": [
    {
      "symbol": "510300",
      "name": "沪深300ETF",
      "factor_summary": "动量因子+0.8σ，估值因子+0.3σ，流动性充足",
      "tech_signal": "MACD金叉，RSI中性偏强(58)，偏多信号",
      "risk_flag": null
    }
  ],
  "risk_warnings": [
    {
      "type": "concentration|drift|correlation|volatility|liquidity",
      "severity": "high|medium|low",
      "description": "行业集中度过高（半导体+AI合计35%），若板块回调将拖累组合",
      "affected_symbols": ["512480", "561300"]
    }
  ]
}
```

# 规则

1. **summary**: 直接给出结论，禁止开场白/自我引荐，2-3句话
2. **suggestions**: 至少 2 条，最多 5 条：
   - increase/decrease: 调整现有持仓权重
   - add/remove: 新增或剔除标的
   - hold: 维持现状
3. **因子引用**: 因子评分 > 0.5σ 才算显著，reason 中注明具体因子名称
4. **risk_warnings**: 从 holdings_analysis 中推断，非凭空编造：
   - concentration: 行业集中度过高
   - drift: 权重偏离阈值
   - correlation: 高相关品种集中
   - volatility: 波动率异常
   - liquidity: 流动性不足
5. **数值格式**: 所有权重值用小数（0.30 = 30%），涨跌幅用小数（-0.03 = -3%）
6. **置信度**: high 必须引用具体数据支持
```

### 3.4 Phase 2: 新增 LLM 调用函数

#### 文件: `backend/app/analysis/llm.py`

```python
async def generate_strategy_check_report(
    market_data: list[dict],
    factor_breakdowns: dict[str, dict],
    regime: str,
) -> dict:
    """基于持仓数据 + 因子分 + regime 生成结构化策略检查报告。"""

    # 格式化持仓数据
    holdings_lines = []
    for item in market_data:
        sym = item.get("symbol", "")
        if sym == "CASH":
            continue
        fb = factor_breakdowns.get(sym, {})
        fs = fb.get("factor_scores", {})
        sig = fb.get("technical_signal", {})
        drift = fb.get("weight_drift", {})

        factor_text = "；".join(
            f"{k}: {v:.2f}" for k, v in sorted(fs.items(), key=lambda x: -abs(x[1]))[:5]
        ) if fs else "无因子数据"
        signal_text = sig.get("signal", "hold")
        drift_text = f"偏离 {drift.get('drift_pct', 0):.1f}%" if drift else "—"

        holdings_lines.append(
            f"- {item.get('name', sym)}({sym}): "
            f"权重 {item.get('target_weight', 0)*100:.0f}%, "
            f"{drift_text}；"
            f"技术信号 {signal_text}；"
            f"因子评分: {factor_text}"
        )

    holdings_text = "\n".join(holdings_lines)
    overview = _build_market_overview(
        [d for d in market_data if d.get("asset_type") == "index"],
        [d for d in market_data if d.get("asset_type") == "commodity"],
        [d for d in market_data if d.get("asset_type") == "stock"],
        [], [],
    )

    prompt = f"""{overview}

## 市场状态
当前 regime: {regime}

## 持仓分析
{holdings_text}

请按 strategy_check.md 要求的 JSON 格式输出分析报告。
"""

    from ..analysis.registry import get_agent
    try:
        return await get_agent("strategy_check").run_json(prompt)
    except Exception as e:
        logger.warning("[strategy_check] LLM analysis failed: %s", e)
        return {
            "summary": "LLM 分析暂不可用，请稍后重试",
            "suggestions": [],
            "holdings_analysis": [],
            "risk_warnings": [],
        }
```

### 3.5 Phase 2: 注册 Agent

#### 文件: `backend/app/analysis/registry.py`

在 `AGENTS` 字典中追加：

```python
"strategy_check": AgentConfig(
    name="策略检查",
    system_prompt_file="strategy_check.md",
    temperature=0.1,              # 低温度确保稳定性
    response_format="json_object",
    max_retries=1,
),
```

### 3.6 Phase 3: 前端结果展示

#### 文件: `frontend/src/components/DashboardAiTools.vue`

在策略 feature card 的 `v-else-if` 链后追加结果渲染区：

```html
<!-- 策略检查结果 -->
<div v-else-if="activeCoreFeature === 'strategy' && checkingStrategy" class="panel-body">
  <div class="loading-section">
    <span class="loading-spinner">&#9203;</span>
    <span>正在分析当前组合...</span>
  </div>
</div>

<div v-else-if="activeCoreFeature === 'strategy' && strategyResult" class="panel-body">
  <div class="strategy-result">

    <!-- 头部: 标题 + 市场状态 + 关闭 -->
    <div class="sr-header">
      <h3>策略检查结果</h3>
      <span class="regime-badge" :class="'regime-' + strategyResult.market_regime">
        {{ regimeLabel(strategyResult.market_regime) }}
      </span>
      <button class="sr-close" @click="exitCoreFeature">&times;</button>
    </div>

    <!-- 综述 -->
    <div class="sr-summary">{{ strategyResult.summary }}</div>

    <!-- 风险预警 -->
    <div v-if="strategyResult.risk_warnings?.length" class="sr-section">
      <h4>&#9888; 风险预警</h4>
      <div v-for="w in strategyResult.risk_warnings" :key="w.type + w.severity"
           class="risk-item" :class="'risk-' + (w.severity || 'medium')">
        <span class="risk-type">{{ riskTypeLabel(w.type) }}</span>
        <span>{{ w.description }}</span>
      </div>
    </div>

    <!-- 操作建议 -->
    <div v-if="strategyResult.suggestions?.length" class="sr-section">
      <h4>&#128200; 操作建议</h4>
      <div v-for="s in strategyResult.suggestions" :key="s.symbol" class="suggestion-card">
        <div class="sc-header">
          <span class="action-badge" :class="'action-' + s.action">
            {{ actionLabel(s.action) }}
          </span>
          <strong>{{ s.name }}</strong>
          <code>{{ s.symbol }}</code>
          <span class="weight-change">
            {{ (s.current_weight * 100).toFixed(0) }}% &rarr; {{ (s.suggested_weight * 100).toFixed(0) }}%
          </span>
        </div>
        <p class="sc-reason">{{ s.reason }}</p>
        <span class="confidence-tag" :class="'conf-' + (s.confidence || 'medium')">
          {{ confidenceLabel(s.confidence) }}
        </span>
      </div>
    </div>

    <!-- 持仓明细表 -->
    <div v-if="strategyResult.holdings_analysis?.length" class="sr-section">
      <h4>&#128202; 持仓明细分析</h4>
      <table class="holdings-table">
        <thead>
          <tr>
            <th>标的</th>
            <th>代码</th>
            <th>因子评分</th>
            <th>技术信号</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="h in strategyResult.holdings_analysis" :key="h.symbol">
            <td>{{ h.name }}</td>
            <td><code>{{ h.symbol }}</code></td>
            <td class="td-factor">{{ h.factor_summary }}</td>
            <td :class="'td-signal signal-' + signalClass(h.tech_signal)">
              {{ h.tech_signal }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="sr-actions">
      <AppButton variant="ghost" @click="exitCoreFeature">返回</AppButton>
    </div>
  </div>
</div>
```

配套在 `<script setup>` 中新增：

```javascript
// 市场状态标签
function regimeLabel(regime) {
  const labels = {
    bull_strong: '强牛市', bull_weakening: '牛市趋弱',
    range_bound: '震荡', correction: '回调',
    bear: '熊市', defensive_rotate: '防御轮动', panic: '恐慌',
  }
  return labels[regime] || regime || '未知'
}

function actionLabel(action) {
  return { increase: '增配', decrease: '减配', hold: '持有',
           add: '新增', remove: '剔除' }[action] || action
}

function confidenceLabel(c) {
  return { high: '高置信度', medium: '中置信度', low: '低置信度' }[c] || c
}

function riskTypeLabel(type) {
  return { concentration: '集中度', drift: '偏离', correlation: '相关性',
           volatility: '波动', liquidity: '流动性' }[type] || type
}

function signalClass(signal) {
  if (!signal) return 'neutral'
  if (signal.includes('买') || signal === 'buy') return 'buy'
  if (signal.includes('卖') || signal === 'sell') return 'sell'
  return 'neutral'
}
```

---

## 4. 文件变更清单

| 文件 | 改动类型 | 行数（估） |
|------|---------|-----------|
| `backend/app/services/portfolio_service.py` | **重构** | ~+120 / -30 |
| `backend/app/analysis/llm.py` | **新增函数** | ~+50 |
| `backend/app/analysis/registry.py` | **追加配置** | +3 |
| `backend/app/analysis/prompts/v1/strategy_check.md` | **新增** | ~+100 |
| `frontend/src/components/DashboardAiTools.vue` | **修改** | ~+120 模板 + 样式 |
| `backend/app/models/schemas.py` | **可选** | ~+30（扩展 StrategyCheckResponse） |

**总计**: +约 420 行，-约 30 行。

---

## 5. 风险与缓解

| 风险 | 可能性 | 缓解 |
|------|--------|------|
| `factor_registry.compute()` 外部数据获取失败 | 中 | 降级为仅返回 indicators，不阻断 |
| `compute_etf_trends()` 耗时过长 | 中 | 45s 超时；超时后 regime 默认 range_bound |
| LLM JSON 解析失败 | 低 | `run_json()` 内置 `_extract_json()` 兜底 |
| `strategy_check_v1` 前端兼容 | 低 | 路由不变，response schema 做后向兼容 |
| 持仓被其他操作同时修改 | 低 | `calculate_allocation()` 在当前事务中读取快照 |

---

## 6. 验收条件

1. **单测通过**: `cd backend && python -m pytest` 全部 PASS
2. **E2E 验证**: `python backend/scripts/verify_e2e.py` 全部 PASS
3. **前端可用**:
   - 点击「策略检查分析」→ 显示功能卡片
   - 点击「开始检查」→ 加载状态 → 展示结果页面
   - 结果页面包含: 市场状态徽标 / 综述 / 风险预警（如有）/ 操作建议卡片 / 持仓明细表
   - 点击「返回」→ 回到主面板
4. **因子数据传入**: 后端日志可见 `factor_registry.compute()` 调用记录，返回有效的因子评分
5. **regime 判定**: 结果中的 `market_regime` 与 `detect_market_regime()` 输出一致
6. **suggestions 可消费**: 输出中的 `{action, symbol, suggested_weight}` 可被 `POST /apply-strategy` 消费

---

## 7. 后续扩展（非本次范围）

- **异步化**: 仿 `POST /design-async` 模式，支持 task_id + WS 推送进度
- **组合对比**: 支持同时对比多组设计方案（当前持仓 vs 推荐方案 vs 手动调整）
- **历史趋势**: 记录历次策略检查结果，展示权重变化的时序趋势
- **因子回测**: 对历史策略检查中的建议做回测验证，评估建议质量

# LLM 流式端点数据管道统一方案

> 2026-07-26 · 基于 F1-F5 AI 顾问质量修复 + 市场报告缺少行业数据的审计发现

---

## 一、现状问题

目前有三个独立的 LLM 数据采集路径，**数据覆盖不一致**：

| 端点 | 行业动量 | 资金流向 | 因子评分 | 市场情绪 | 实时行情 | 资讯 | 组合 |
|------|:--------:|:--------:|:--------:|:--------:|:--------:|:----:|:----:|
| **AI 顾问** `llm_advice_stream` | ✅ F1 | ✅ F2 | ❌ | ✅ | ✅ | ✅ | ✅ |
| **市场报告** `llm_report_stream` | ❌ | ❌ | ❌ | ✅ | ✅ | ✅ | ❌ |
| **组合设计报告** `design_report.py` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

每个端点自己 `try/except` 包裹采集逻辑，加数据要改 N 处。

---

## 二、统一方案

### 核心设计

新增 `_build_full_context()` 公共数据管道函数：

```python
# 位置: backend/app/services/pool_manager.py 或新建 backend/app/services/llm_context.py

async def build_full_context(
    include_regime: bool = True,
    include_indices: bool = True,
    include_sectors: bool = True,
    include_news: bool = True,
    include_portfolio: bool = True,
    include_fund_flow: bool = True,
    include_factors: bool = False,  # 因子矩阵数据量大，默认关闭
) -> dict:
    """统一的 LLM 上下文数据采集。

    返回:
      {
        "market_regime": str,
        "market_sentiment": {"sentiment_index": int, "sentiment_label": str},
        "index_realtime": [{"name": str, "price": float, "change_pct": float}, ...],
        "sector_momentum": [{"sector_name": str, "change_pct": float, "rank": int}, ...],
        "realtime_etfs": [{"symbol": str, "name": str, "price": float, ...}, ...],
        "news": [{"title": str, "summary": str, ...}, ...],
        "fund_flow": {"total_net_inflow": float, "positive_flow_count": int, ...},
        "factor_summary": [{"symbol": str, "top_factors": [(str, float), ...]}, ...],
        "portfolio": [{"symbol": str, "name": str, "target_weight": float, ...}, ...],
        "commodities": [{"symbol": str, "name": str, "price": float, ...}, ...],
        "error": str | None,  # 非致命错误
      }
    """
```

### 数据来源映射

| 字段 | 数据源 | 容错方式 |
|------|--------|---------|
| `market_regime` | `pool_manager.get_market_regime()` | `try: except: ""` |
| `market_sentiment` | `pool_manager.get_market_sentiment()` | `{}` |
| `index_realtime` | `pool_manager.get_index_realtime()` → 取前 10 个 | `[]` |
| `sector_momentum` | `pool_manager.get_sector_momentum()` → 取前 15 个 | `[]` |
| `realtime_etfs` | `get_all_realtime()` → 按 asset_type 过滤 | `[]` + asyncio.wait_for 15s |
| `news` | `fetch_news_headlines()` + `fetch_macro_news()` | `[]` + to_thread |
| `fund_flow` | `strategy_design._compute_fund_flow(pool_manager)` | `{}` |
| `factor_summary` | `pool_manager.get_factor_matrix()` → 取前 5 只 ETF 的 top-3 因子 | `[]` |
| `portfolio` | `portfolio_service.get_all_holdings()` | `[]` |
| `commodities` | `get_commodities()` | `[]` |

### Prompt 构建模板化

各端点在调用 `build_full_context()` 后，根据自身需求选择字段来构建 prompt：

```python
# 统一 prompt 模板位置: backend/app/analysis/prompts/v1/
#
# llm_advice.prompt      → AI 顾问 prompt 框架
#   - 注入: regime, sentiment, indices, sector_momentum, news, fund_flow, portfolio
#
# llm_report.prompt      → 市场研判报告 prompt 框架
#   - 注入: regime, sentiment, indices, commodities, sector_momentum, news, fund_flow
#
# design_report.md       → 组合设计报告 prompt 框架（已有）
#   - 注入: 全部
```

---

## 三、实施步骤

| 步骤 | 内容 | 文件 | 预估 |
|:----:|------|------|:----:|
| 1 | 新增 `build_full_context()` 函数 | `backend/app/services/`（新建 llm_context.py 或放入 pool_manager.py） | ~60行 |
| 2 | 改造 `llm_report_stream`：改用 `build_full_context` 替代自采 + `generate_market_report` 改用结构化 context | `backend/app/routers/analysis.py` + `backend/app/analysis/llm.py` | ~40行 |
| 3 | 改造 `llm_advice_stream`：改用 `build_full_context` + `_build_advice_stream_prompt` 从统一 context 读取 | `backend/app/routers/analysis.py` | ~20行 |
| 4 | 可选：因子摘要从 `build_full_context` 批量注入 | `backend/app/routers/analysis.py` + `backend/app/analysis/llm.py` | ~10行 |
| 5 | 新增 `llm_advice.prompt` 模板文件，迁移 `_build_advice_stream_prompt` 逻辑 | `backend/app/analysis/prompts/v1/llm_advice.prompt` | ~40行 |
| 6 | 验证：npm test + 后端单测 + 流式数据链路实测 | — | ~15min |

**总预估**：~170 行 / 2-3 小时

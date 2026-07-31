# ETF Surge — Z 系列问题修复设计 v5.3（Z22 / Z25 / Z26 / Z05 / Z03 / Z11 / Z20）

> 生成时间: 2026-07-31
> 依据: `docs/v5_diagnostic_and_optimization_plan.md` + 全链路代码实证（本轮调查）
> 状态: **设计稿，尚未实施**。经过多轮 review 达到实施标准后，按本文档逐步实施。
> 范围: 仅设计。本文档不包含任何代码改动。

---

## 0. 总览

| ID | 问题（用户口径） | 根因（实证） | 修复策略 | 自动验证 |
|----|-----------------|-------------|---------|---------|
| Z22 | 历史脏数据条目（symbol 存名称）仍无法填充，新添加的已正常 | 写入零校验 + 读取按代码精确匹配 + 无名称→代码解析 | 读取侧名称解析+自愈回写；写入侧校验拦截新增 | 单测 + verify_e2e watchlist 用例 |
| Z25 | 热门个股有 price 但缺 volume/sector | levistock 补全仅请求 f2/f3/f4/f12，repo 单源透传 | repo 侧二次 enrich（volume 批量行情 + sector 行业映射） | 单测 mock + verify_e2e 字段断言 |
| Z26 | 策略检查覆盖率依赖 LLM 响应稳定性（超时仍偶发） | 超时预算失配（126s>120s）+ 无规则兜底 + prompt 软约束矛盾 | 规则引擎兜底 + 覆盖校验补齐 + 超时预算修正 | 单测 mock LLM 超时/部分覆盖 |
| Z05 | SSL 连接池已加但握手次数未达 <5 | 连接池是死代码（_get_nav_session 未使用）；39 处 urllib 裸调用；akshare 内部不可注入 | NAV/全局指数路径接入共享 Session；验收口径改为按 host ≤1 | 预热握手计数指标（固化到日志/API） |
| Z03 | API 未暴露分类明细（无法自动验证） | `/active` 已暴露明细但缺样本数/新鲜度/权威状态；硬编码 ic=0 掩盖未计算 | 服务端权威 status+reason+sample_count；移除硬编码 | 单测 + verify_e2e factors 契约 |
| Z11 | 非交易时段未复现（无法自动验证） | 三层静态兜底互不契约；空 factor_matrix 静默均匀权重 | 统一静态池 + fallback 元数据 + 降级形态契约 | 单测（新增场景）+ verify_e2e 弱断言 |
| Z20 | UX 排序（无法自动验证） | 搜索全部 ILIKE+LIMIT 无 ORDER BY，排序不可复现 | 统一分档排序契约（SQL CASE + Python 降级同契约） | 单测 + verify_e2e 顺序断言 |

---

## 1. Z22 — watchlist 历史脏数据（symbol 存名称）无法填充

### 1.1 现状与证据

- 写入：`backend/app/routers/market.py:404-433` `POST /watchlist`。
  - `WatchlistCreate`（`backend/app/models/schemas.py:225-232`）`symbol: str` **无 pattern/长度约束，零校验**。
  - `market.py:416-417`：`realtime = await market_data_hub.get_asset_realtime(data.symbol, data.asset_type)`；`name = realtime.get("name", data.symbol) if realtime else data.symbol`。
  - **symbol 原样入库**；行情查不到时 `name` 也等于 symbol（即中文名）。
- 读取：`backend/app/routers/market.py:358-401` `GET /watchlist`。
  - `market.py:378` 逐条 `realtime = await market_data_hub.get_asset_realtime(item.symbol, item.asset_type)`。
  - `market.py:388-393`：`if realtime:` 才输出 `realtime = {price, change_pct, volume}`；**查不到则整个 realtime 字段缺失**。
- 行情解析：`backend/app/services/market_service.py:906-928` `get_asset_realtime` → `fetch_a_stock_realtime(symbol)`（`backend/app/fetchers/china_market.py:536-543`，mootdx→Sina）→ `_filtered(..., [symbol])` **按代码精确匹配**。中文名称非合法代码 → 空列表 → `None`。
- 委托链：`market_data_hub.get_asset_realtime`（`market_data_hub.py:1309-1313`）→ 同上。
- 前端：`frontend/src/components/market/WatchlistPanel.vue:24-33` 自由输入框，placeholder **"搜索代码或名称，如 510050、贵州茅台..."**；`:243-247` 建议选中才写入代码，用户直接回车提交中文名 → 脏数据。
- **DB 实证**（`E:\ETF_Surge\data\portfolio.db`，2026-07-31 只读查询）：
  - id=1 `symbol='贵州茅台'`（**名称**）、name='贵州茅台'、asset_type='A'、created=2026-07-22 → 脏数据，price/change_pct/volume 为 null
  - id=2 `symbol='510300'` 正常
  - id=3 `symbol='600519'`、**name=''（空串）**、created=2026-07-31 → 附带新缺陷：`realtime.get("name", symbol)` 当 name 键存在但为 `''` 时返回空串
- 名称→代码反查通道现状：
  - `instruments` 表（`backend/app/models/search.py:15-27`）：1544 条**全部为 ETF**（asset_type='etf'），**无个股行** → `/search/stocks` 的 DB 路径（`market.py:117-157` 查 `asset_type=='stock'`）恒空，走降级 `get_all_stocks`（levistock `stocks_all_em`，全量 A 股，含 `stock_code`/`stock_name`）。
  - `market_service.search_etf`（`market_service.py:531-576`）：只查 ETF instruments + akshare ETF 列表，**不含个股**。
  - 结论：个股名称→代码反查只能依赖 `get_all_stocks`（levistock/akshare 双源，`sector_fetcher.py:314-321`）。

### 1.2 根因

1. **写入侧零校验**：前端允许输入名称，后端照单全收，`symbol` 列存中文名称。
2. **读取侧无名称解析**：实时行情链路只认代码，名称永远返回 None → 历史脏条目字段永远 null。
3. `name` 空串缺陷：`dict.get(key, default)` 不处理"键存在但值为空"。

### 1.3 修复设计

#### ① 写入侧校验（拦截新增脏数据）

- **schema 层**：`WatchlistCreate`（`backend/app/models/schemas.py:225-232`）增加 `symbol: str = Field(..., min_length=1, max_length=20, pattern=r"^[0-9A-Za-z.\-]+$")`，**拒绝中文/空格**（A 股 6 位数字、美股字母、港股 `xxxxx.HK` 均符合）。
- **router 层**：`POST /watchlist`（`market.py:404-433`）在入库前调用 `market_data_hub.get_asset_realtime(symbol, asset_type)`：
  - 返回 None → `HTTPException(422, "无法解析该标的，请通过搜索选择")`，不落库。
  - 返回数据但 name 为空 → `name = realtime.get("name") or symbol`（修复空串）。
- **前端层**（配合）：`WatchlistPanel.vue` 对未选中建议的直接提交做二次确认，或复用后端 422 提示；placeholder 文案改为"搜索代码或名称（将自动匹配为代码）"。

> 边界：既有脏条目不受 schema 影响（schema 只约束新请求）。`asset_type` 默认值不一致（schema `"etf"` vs 模型 `"A"`）顺带在 `WatchlistBase` 统一为 `"A"`（与模型默认一致），前端显式传参不受影响。

#### ② 读取侧名称解析 + 自愈回写（治历史脏数据）

在 `GET /watchlist`（`market.py:358-401`）的逐条循环中增加解析与自愈：

```
for item in items:
    realtime = await get_asset_realtime(item.symbol, item.asset_type)
    resolved_symbol = None
    if realtime is None and 不是合法代码形态(item.symbol):
        resolved_symbol = await resolve_symbol_to_code(item.symbol, item.asset_type)  # 名称→代码
        if resolved_symbol:
            realtime = await get_asset_realtime(resolved_symbol, item.asset_type)     # 用真代码重查行情
    # 注：不提供"合法代码查不到时批量重试"第三层（get_asset_realtime 内部已有 mootdx→Sina 降级）
    if resolved_symbol and resolved_symbol != item.symbol:
        回写 item.symbol = resolved_symbol; item.name = item.name or realtime.name  # 自愈
        await session.commit()
    ...
```

- **`resolve_symbol_to_code(symbol, asset_type)`**（新增，放 `backend/app/services/market_service.py`，与 `search_stocks` 同层；纯查询，无副作用）：
  1. `instruments` 表：`name == symbol`（精确）→ `name LIKE %symbol%`（模糊），取 symbol；命中即返回。ETF 用此路径（`/search` 现成逻辑复用）。注：`instruments` 当前仅 ETF 行，个股在此表查不到（走 2）。
  2. 降级：`get_all_stocks()`（`sector_fetcher.fetch_all_stocks`，levistock→akshare 双源，**全量 A 股**）按 `stock_name == symbol`（精确）→ 包含匹配，取 `stock_code`。仅 `asset_type=="A"` 时走此路径；名称匹配排序遵循 Z20 的统一排序契约（`_sort_results`），取首条。
  3. 无命中 → 返回 None（保持现状：realtime 缺失，前端显示空）。
- **合法代码形态判断**：`re.fullmatch(r"[0-9]{6}(\.HK)?|[A-Z]{1,5}(-|\.)?[A-Z]*", symbol)` 之类——目的只是"看起来像代码就不去解析"（避免对 `510300` 这类正常代码做无谓的名称查询）。美股/港股本就按代码存储，无需解析。
- **自愈回写**：解析成功 → `UPDATE watchlist SET symbol=:resolved, name=COALESCE(NULLIF(name,''), :realname) WHERE id=:id`。
  - 唯一约束风险：若该代码已被另一条目占用（`symbol` unique），回写会抛 IntegrityError → 捕获后**放弃回写**（仅本次响应用解析结果），记 warning 日志；不阻塞响应。
  - 回写范围：仅对"符号形态非法 + 解析成功"的条目，次数受控（每条一次）。
- **批量优化**（可选，P2）：`GET /watchlist` 逐条 `get_asset_realtime` 是 N 次串行外部调用。已有 `get_realtime_batch`（`market_service.py:745-775`，仅 A 股，带行情缓存）。可改为：先批量查一次全部合法代码 → 名称条目再逐个解析 → 批量查解析结果。本期如行数少可保持串行，但设计上预留批量路径。注意 `get_asset_realtime` 内部已做 mootdx→Sina 两级降级，**不做**"代码查不到时再用批量重试"的第三层（收益低、复杂度高）；批量路径只用于整体减少串行次数。

#### ③ 附带修复：id=3 类 name 空串

`market.py:417` 与 `market_service.py:1078`（`add_watchlist`）统一为 `name = (realtime.get("name") or "").strip() or symbol`。

### 1.4 验收标准（自动验证）

- **单测**（新增 `backend/tests/test_watchlist_dirty.py`）：
  1. mock `get_asset_realtime` 返回 None + mock `resolve_symbol_to_code` 返回 "600519" → 断言响应包含 price/change_pct/volume 且 DB 中 symbol 已回写为 600519。
  2. mock 解析失败 → 响应无 realtime 字段，DB 不变（不抛错）。
  3. 回写遇 unique 冲突 → 响应仍含解析行情，DB 不变，无异常。
  4. schema 校验：`POST /watchlist` 传中文 symbol → 422。
  5. 新条目 name 空串兜底：mock realtime 返回 `{"name": ""}` → 落库 name = symbol。
- **verify_e2e**（`section_portfolio` 或新增 `section_watchlist`）：
  1. `GET /watchlist` 全量：对每个 `symbol` 非代码形态的条目，断言其响应包含 `realtime.price` 非 null（若数据源可用）。
  2. 断言 DB 无新增中文 symbol（写入侧校验生效的回归哨兵）。

---

## 2. Z25 — 热门个股有 price 但缺 volume/sector

### 2.1 现状与证据

- 端点链：`GET /stock-hot-rank`（`routers/market.py:342-345`）→ `market_data_hub.get_stock_hot_rank`（`market_data_hub.py:1389-1396`，异常返回 `[]`）→ `sector_fetcher.fetch_stock_hot_rank`（`sector_fetcher.py:336-340`）。
- 数据源：`lv.stock_hot_rank_ths(limit)`（levistock 包，`stock_hot_ths.py`）：
  - 同花顺热度榜（`dq.10jqka.com.cn`）返回 rank/code/name/tag；
  - 东财 ulist 补全（`push2delay.eastmoney.com/api/qt/ulist.np/get`）**fields 仅 `f2,f3,f4,f12`**（现价/涨跌幅/涨跌额/代码）—— 无 `f5`（成交量）、无 `f100`（行业）。证据：`backend/logs/backend.log.5:670` 真实请求日志。
- repo 侧 `fetch_stock_hot_rank` **单源透传**，无 akshare 降级（对照同文件 `fetch_all_stocks` 的 `_try_two`），无字段补全/行业 join。
- 可用通路（未接线）：
  - `fetch_a_stock_batch`（`china_market.py:546-554`，mootdx→Tencent→Sina 批量）→ volume。
  - `fetch_all_stocks`（`sector_fetcher.py:314-321`，levistock `stocks_all_em` 全量 A 股，含 volume 等；`_ak_all_stocks` 为 akshare 降级）→ volume + 名称映射。**无行业字段**。
- 前端：`frontend/src/components/market/SectorHeatMap.vue:74-92,148-150` 仅渲染 name/symbol/change_pct；`frontend/src/api/index.js:44`。
- 契约：`api-contracts/market/hot-plates.md:62-83` 仅承诺 symbol/name/price/change_pct。

### 2.2 根因

字段缺失发生在**外部 levistock 包内**（东财补全请求 fields 不含 f5/f100），repo 侧无补全层。price 能显示纯属 levistock 内部恰好补了 f2/f3/f4。

### 2.3 修复设计（repo 侧，不改外部库）

#### ① volume 补全：复用 `fetch_a_stock_batch`

`fetch_stock_hot_rank`（`sector_fetcher.py:336-340`）改为两段式：

```python
def fetch_stock_hot_rank(limit=50):
    def _p():
        rows = lv.stock_hot_rank_ths(limit) or []
        return _enrich_hot_rank(rows)   # 新增：二次补全
    return _cached("stock_hot_rank", _p, "sector_heat")
```

```python
def _enrich_hot_rank(rows):
    codes = [r["code"] for r in rows if r.get("code")]
    # volume 补全：腾讯/新浪批量（复用现有熔断链，8s 超时）
    quotes = china_market.fetch_a_stock_batch(codes)  # 或经 source_registry 路由
    qmap = {q["symbol"]: q for q in quotes}
    for r in rows:
        q = qmap.get(r["code"])
        if q:
            r["volume"] = q.get("volume")
            if not r.get("price") or r.get("price") == 0:
                r["price"] = q.get("price")
                r["change_pct"] = q.get("change_pct")
    # sector 补全（见 ②）
    sec_map = _get_stock_industry_map()
    for r in rows:
        r["sector"] = sec_map.get(r["code"]) or sec_map.get(r["name"]) or None
    return rows
```

- 超时/失败策略：`fetch_a_stock_batch` 与行业映射均带超时与异常兜底，**失败时 volume/sector 保持 null，绝不阻塞**（基础字段 name/price/change_pct 保留）。
- 上下文说明：`sector_fetcher` 顶层函数是同步的（被 `_cached` 包装，调用方经 `asyncio.to_thread`/`_exec` 在线程中执行），`fetch_a_stock_batch`（`china_market.py:546`）同为同步函数且内部走 registry 熔断路由——**在 `_enrich_hot_rank` 中直接同步调用即可，无需再套线程**；`_get_stock_industry_map` 经 `_exec`（timeout=10）调用。
- 缓存：`_enrich_hot_rank` 结果已由外层 `_cached` 缓存（sector_heat TTL）。

#### ② sector 补全：新增东财 clist 行业映射（一次请求）

新增 `sector_fetcher._get_stock_industry_map()`（缓存 6h）：

```python
def _get_stock_industry_map() -> dict[str, str]:
    """代码/名称 → 行业名 映射。东财 clist 一次请求全量 A 股（f12 代码, f100 行业）。"""
    # GET http://push2delay.eastmoney.com/api/qt/clist/get
    #   ?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f100
    # 返回 {"000001": "银行", ...}，走 _exec() 线程 + timeout，缓存 6h
```

- 降级：请求失败 → 返回 `{}`（sector 为 null）；akshare 兜底（可选 P2）：遍历 `ak.stock_board_industry_name_em()` + `stock_board_industry_cons_em` 建映射（90+ 次请求，成本高，仅作最后手段或夜间后台任务）。
- 字段名：热度行统一输出 `sector`（字符串），与前端字段对齐。

#### ③ 契约更新

`api-contracts/market/hot-plates.md` 的 stock-hot-rank 响应增加 `volume`（float，可 null）、`sector`（string，可 null）；明确"数据源不可用时允许为 null，不视为错误"。

#### ④ 前端展示（P2）

`SectorHeatMap.vue` 热度榜增加成交量/行业列（`v-if="item.volume != null"` 等空态保护）。本期可仅后端 + 契约，前端展示作为独立小改动。

### 2.4 验收标准

- **单测**（`backend/tests/test_stock_hot_rank.py`）：
  1. mock `lv.stock_hot_rank_ths` 返回 3 条基础字段 → mock `fetch_a_stock_batch` 返回含 volume → 断言输出含 volume。
  2. mock `fetch_a_stock_batch` 抛异常/空 → 断言 volume 为 null、基础字段保留、无异常。
  3. mock 行业映射含 `{"000001": "银行"}` → 断言 sector 填充；映射缺该代码 → sector null。
- **verify_e2e**（`section_market` 增强）：
  1. `GET /stock-hot-rank?limit=50` → 200，条数 ≥1。
  2. 对前 5 条断言存在 `code`/`name`；存在 `volume` 或 `volume is None` 但 `price` 非 null（字段形态契约）。
  3. 弱断言：**50 条中 ≥80% 有 volume**（数据源正常时的回归门禁，允许个别缺失）。

---

## 3. Z26 — 策略检查覆盖率依赖 LLM 响应稳定性

### 3.1 现状与证据

- 链路：`strategy_check_worker.py:64-99`（外层 `asyncio.wait_for(_pipeline_body, timeout=120)`）→ `portfolio_service.strategy_check`（`:354-579`）→ `generate_strategy_check_report`（`llm.py:970-1052`）→ `get_agent("strategy_check").run_json`（`analysis/runtime.py`）。
- 超时失配：LLM 最坏耗时 = (primary 30s + fallback 30s + retry delay 3s) × 2 轮 ≈ **126s > 外层 120s** → 整单 `failed`，`partial_data:{}`（`strategy_check_worker.py:80-89`）。
- 无规则兜底：`portfolio_service.py:562` `result["suggestions"] = llm_result.get("suggestions", [])` 直接透传；LLM 超时/异常 → `llm.py:1045-1052` 返回空 dict。**risk_warnings 有规则兜底**（`:564-567` `_combine_risk_warnings` + `_compute_risk_warnings`），**suggestions/holdings_analysis 无兜底、无覆盖校验**。
- Prompt 矛盾：`llm.py:1034` "**必须**覆盖每个持仓标的至少一条建议" vs 系统 prompt `prompts/v1/strategy_check.md:12` "**尽量**覆盖主要持仓标的…可简略处理"；`min_suggestions = max(3, holdings_count // 2)`（`:1007`）仅要求半数。
- 部分覆盖路径：LLM 正常返回但跳过部分标的 → 后处理（`:511-539`）只对已返回的 holdings_analysis 回填数据，**不补缺失标的**。
- 数据采集：`asyncio.wait_for(..., timeout=30)`（`:411-414`），超时用部分数据（可接受）。

### 3.2 根因

1. LLM 单次调用最坏耗时（~126s）与外层预算（120s）失配 → 超时即整单空结果。
2. suggestions/holdings_analysis 完全依赖 LLM 输出：无规则兜底、无覆盖校验。
3. prompt "尽量覆盖"与"必须覆盖"语义冲突，`min_suggestions` 允许合法跳过半数标的。

### 3.3 修复设计

#### ① 规则引擎兜底（核心，纯函数，可单测）

新增 `backend/app/engine/strategy_rules.py`（与现有 `engine/` 纯函数包风格一致，无 I/O）：

```python
def build_rule_suggestions(
    market_data: list[dict],           # 持仓（含 symbol/name/target_weight）
    factor_breakdowns: dict[str, dict],# sym -> {factor_scores, technical_signal, weight_drift}
    regime: str,
) -> dict:
    """为每个非 CASH 持仓生成规则建议，保证 100% 覆盖。

    规则（v1，可调阈值；σ 先截断到 ±3 再判阈值，避免 Z09 极端 σ 放大信号）：
      - factor_scores 中综合/动量/趋势类因子 σ >= +1.5  → increase（增持）
      - σ <= -1.5  → decrease（减持）
      - weight_drift.drift_pct 超阈值（如 |drift|>20%）→ 按偏离方向给出调仓动作
      - 技术信号 signal == "sell" 且 σ 为负 → decrease；signal == "buy" 且 σ 为正 → increase
      - 其余 → hold（持有）
    输出: {suggestions: [...], holdings_analysis: [...]}

    **字段契约对齐（关键）**：输出必须匹配 `prompts/v1/strategy_check.md:25-48` 的 JSON schema——
      suggestions[].action 取值 **increase|decrease|hold**（规则引擎不产生 add/remove），
      并带 symbol/name/current_weight/suggested_weight/reason/confidence；
      holdings_analysis[].symbol/name/weight/factor_summary/tech_signal/risk_flag。
    suggested_weight 规则：increase → min(current + 0.03, 0.30)；decrease → max(current - 0.03, 0.0)；hold → current。
    """
```

- confidence 复用现有 `_compute_confidence`（数据覆盖率）；reason 用中文模板 + 因子名（如 `"动量因子 -2.1σ，建议减持"`）。
- 与 `engine/rationale.py` 风格一致，模板多样化（避免每次文案雷同）。
- **架构约束**：`engine/` 为纯函数包（无 I/O、无外部依赖），**不得 import services 层**。因此 confidence 计算逻辑（`_compute_confidence`，现位于 `portfolio_service.py:539`）需**内联复制**到 `strategy_rules.py` 内（纯函数），或由调用方 `portfolio_service` 在合并时统一回填 confidence（推荐后者，见 ②——规则条目合并进 result 后，由现有后处理统一计算 confidence，避免逻辑重复）。

#### ② 覆盖校验后处理（兜底合并，保证全持仓至少一条）

`portfolio_service.strategy_check` 在 `llm_result` 拿到后、组装 `result` 前增加：

```python
rule_result = build_rule_suggestions(market_data, factor_breakdowns, regime)  # 始终计算（幂等、无 I/O）

# 1) holdings_analysis 补齐：LLM 覆盖的 symbol 集合 ∪ rule 全量 → 缺失标的用 rule 条目补
llm_syms = {h.get("symbol") for h in llm_result.get("holdings_analysis", [])}
for h in rule_result["holdings_analysis"]:
    if h["symbol"] not in llm_syms:
        h["source"] = "rule_fallback"
        llm_result["holdings_analysis"].append(h)

# 2) suggestions 补齐：确保每个非 CASH 持仓在 suggestions 的 name/symbol 中出现
sugg_syms = {s.get("symbol") or s.get("name") for s in llm_result.get("suggestions", [])}
for s in rule_result["suggestions"]:
    if s["symbol"] not in sugg_syms:
        s["source"] = "rule_fallback"
        llm_result["suggestions"].append(s)

# 3) 摘要标记：发生兜底时 summary 追加 "（部分建议由规则引擎生成）"
if 任一 rule_fallback 条目: llm_result["summary"] = ... + "；部分建议基于因子数据由规则引擎生成"
```

- 逻辑位置：`portfolio_service.py:476-499`（LLM 调用）之后、`:501` 现有后处理循环（P2-1 回填）**之前**插入合并——这样规则条目同样能获得 weight/因子分/confidence 回填；新增辅助函数 `_ensure_full_coverage(llm_result, rule_result)`（放同一文件，纯逻辑，可单测）。
- LLM 完全失败（空 dict）时：`_ensure_full_coverage` 直接产出全量规则结果 → **覆盖率 100%，不再是空报告**。

#### ③ 超时预算修正

- `portfolio_service.py:476-483`：LLM 调用改包 `asyncio.wait_for(..., timeout=90)`（覆盖 provider failover 全程），超时走现有 `except asyncio.TimeoutError` 分支（此时规则兜底保证有内容）。
- `strategy_check_worker.py:78`：外层 120s → **150s**（数据 30s + LLM 90s + 后处理/落库余量 30s），消除预算临界。
- 顺带：`strategy_check_worker.py:238` 报告生成 `wait_for(..., 20)` 保持。

#### ④ Prompt 统一（消除语义冲突）

- `llm.py:1034` 保留"必须覆盖每个持仓标的至少一条建议"。
- `prompts/v1/strategy_check.md:12` 改为："**必须**对每个持仓标的给出至少一条建议（action 取 increase/decrease/hold），不允许省略任何标的；因子数据缺失的标的基于权重与相关性给出 hold/观察建议并降低置信度"。
- `min_suggestions` 由 `max(3, holdings_count // 2)` 提升为 **`holdings_count`**（全覆盖），`max_suggestions` 保持档位（5/8/12）——若 holdings_count > max，以 max 为上限但**通过规则兜底补齐覆盖**（不依赖 LLM 自觉）。

### 3.4 验收标准

- **单测**（`backend/tests/test_strategy_check_coverage.py`）：
  1. mock `generate_strategy_check_report` 抛 `asyncio.TimeoutError` → 断言 `strategy_check` 返回的 suggestions 覆盖**全部**持仓（含 CASH 外的每一只），且存在 `source="rule_fallback"` 条目。
  2. mock LLM 返回仅覆盖 2/5 标的 → 断言补齐后 5/5，LLM 条目保持 `source` 无标记，补齐条目有标记。
  3. 规则函数纯测：给定 σ=+2.0 → action=increase；σ=-2.0 → decrease；σ=0 且无 drift → hold；drift>20% → 调仓动作；并断言输出字段符合 strategy_check.md schema（含 current_weight/suggested_weight）。
  4. 超时预算：断言 `strategy_check` 内 LLM 调用被 `wait_for(90)` 包裹（mock 后验证超时参数）。
- **verify_e2e**（`section_portfolio` 或 `section_async_resilience`）：
  1. 触发一次策略检查任务 → 完成后 `GET /tasks/{id}` 断言 `status=="completed"`。
  2. 结果 `suggestions` 数量 ≥ 持仓数（或等于 min(持仓数, max_suggestions)），且 `holdings_analysis` 覆盖全部持仓 symbol。

---

## 4. Z05 — SSL 连接池已加但握手次数未达 <5

### 4.1 现状与证据

- 已实现复用（仅 2 处 + 1 处死代码）：
  - `china_market._session()`（`china_market.py:41-63`）：共享 Session + HTTPAdapter(pool_connections=30, pool_maxsize=60)，**6 处调用**（213/261/291/356/687/738）已走它（新浪/腾讯）。
  - `news_fetcher._http_session`（`news_fetcher.py:31-37`）：新闻抓取用。
  - **死代码**：`china_market._get_nav_session()`（`:823-836`）创建 Session 但**从未被调用**；`fetch_fund_nav`（`:839-872`）主路径 `ak.fund_open_fund_info_em`（akshare 内部每次新建连接），fallback `fund_fetcher.fetch_fund_nav`（`fund_fetcher.py:33-43`，`urllib.request.urlopen` 每次新建 TLS）。
- 未复用热点（预热路径）：
  - `global_markets_fetcher.py`：`_td_request`（TwelveData，`:439-450`）、`_request`（Finnhub，`:547-559`）、`_av_request`（`:336-347`）全部 `urllib.request.urlopen`；`_fetch_series`（FRED，`:782`）`httpx.AsyncClient` 每次 `async with` 新建。
  - `etf_scanner.py`：`_fetch_em_etf_list`（`:164-185`，最多 19 页 http）、`enrich_tracked_indices`（`:584-587`，**https** fund.eastmoney.com 页面）裸 `requests.get`。
  - `china_market.py:395-398`（新浪 IOPV）、`:465-476`（网易历史）仍 urllib 裸调。
  - `ttj_fetcher.py`、`fundamentals_fetcher.py`：urllib/akshare 混用。
- **akshare 内部**（`ak.fund_open_fund_info_em`、`ak.index_global_spot_em` 等 20+ 调用点）：内部 `requests.get` 每次新建 Session → 无法从 repo 注入。
- cProfile 证据：`backend/logs/warmup_cprofile.txt`（23 次握手、0.83s）。
- 结论：**预热阶段涉及的 host 包括**：东财（akshare 净值/指数）、新浪、腾讯、同花顺（levistock）、12data、finnhub、天天基金（fund_fetcher fallback）、网易。**绝对"<5 次握手"在当前多 host 架构下不可能达成**（akshare 内部不可控）。

### 4.2 修复设计

#### ① NAV 路径直连共享连接（主修复，收益最大）

`fetch_fund_nav`（`china_market.py:839-872`）调整优先级：

1. **首选**：直连天天基金 HTTP API（`fund_fetcher.fetch_fund_nav` 改造为使用 `china_market._session()` 或自身共享 Session）——10 只 ETF 的 NAV 只产生 **1 次握手**（host 复用）。
2. akshare `fund_open_fund_info_em` 降为 fallback（仅在直连失败时）。
3. 删除死代码 `_get_nav_session`（或改为真正使用），消除"看起来有连接池"的假象。

具体改动：
- `fund_fetcher.py`：模块级共享 `requests.Session`（参照 `_session()`，带 HTTPAdapter 池），`_fetch_nav`/`fetch_fund_nav` 用它替换 `urllib.request.urlopen`。
- `china_market.py:865-872`：fallback 分支用 `fund_fetcher` 的共享 session（或直接 `_session()`）。

#### ② 全局指数/美股路径接入共享连接

- `global_markets_fetcher.py`：新增模块级共享 `requests.Session`（`_td_session` 等或统一一个），`_td_request`/`_request`/`_av_request` 从 `urllib.request.urlopen` 改为 `session.get(...)`（**keep-alive 生效**，TwelveData/Finnhub 各 host 1 连接）。
- `_fetch_series`（FRED）：`httpx.AsyncClient` 提为模块级共享单例（`async with` 改为 `await client.get`），复用连接。

#### ③ etf_scanner / china_market 剩余裸调用

- `etf_scanner.py`：`_fetch_em_etf_list`、`enrich_tracked_indices` 改共享 Session（后者是 https，直接减少握手）。
- `china_market.py:395-398`（新浪 IOPV）、`:465-476`（网易）改 `_session()`（新浪与现有 Sina 请求同 host 复用；网易独立 host 1 连接）。

#### ④ 验收口径调整 + 计数固化（关键）

- **口径调整**（明示，写入文档与契约）：绝对 `<5` 次在 akshare 多 host 场景下不可达，改为：
  - **验收 A（主）**：预热阶段**每个 host 握手 ≤1 次**（排除 akshare/levistock 内部不可控 host），且**总握手 ≤ 可控 host 数 + 1**（预热实际可控 host：新浪 hq.sinajs.cn、腾讯、东财、天天基金、网易等，实测约 5~7 个，故总握手目标 **≤8**，实施时以 warmup 实测日志为准校准；**同花顺/levistock 不在预热路径**）。
  - **验收 B（可测）**：`PROFILE_WARMUP=1` 时预热日志输出 `ssl_handshakes={n}` 计数，供 CI/脚本断言。
- **计数实现**：在预热路径（`main.py:151-217`）用轻量 TLS 计数器：monkeypatch `ssl.SSLContext.wrap_socket` 统计握手次数（预热期间全局计数），或统计 `requests.Session`/urllib 层新建连接数。**推荐**：预热开始时挂 `ssl` 计数钩子（`app/profiling/` 已有 PROFILE_WARMUP 机制，`main.py` 参照），预热结束打印并恢复。
  - 并发说明：lifespan 预热期间后台刷新循环**尚未启动**（main.py 先预热后启后台任务）→ 计数期间无其他线程发起请求，钩子计数可信；若实现时发现后台循环已并发启动，钩子加线程锁并只统计预热阶段时间窗。
- **不推荐**全局 monkeypatch akshare 的 requests（风险：cookie/Referer/并发状态竞争，收益不确定），设计上明确排除，仅在文档记录备选。

### 4.3 验收标准

- **单测**：`fetch_fund_nav` mock 天天基金直连成功 → 断言走直连（不调 akshare）；`fund_fetcher` 使用共享 Session（断言模块级 `_session` 单例被引用）。
- **预热计数**：`PROFILE_WARMUP=1` 启动日志含 `ssl_handshakes`，且数值满足口径 B（总握手 ≤6 或每个 host ≤1；akshare 路径注明"外部不可控"）。**实施后用 warmup 实测修订具体阈值**。
- **verify_e2e**（`section_health` 或预热模块）：不直接断言握手数（依赖环境），改为断言预热日志存在 `ssl_handshakes` 指标行（回归哨兵，防止指标消失）。

---

## 5. Z03 — 因子分类明细（API 未暴露分类明细 / 无法自动验证）

### 5.1 现状与证据

- `GET /api/v1/factors/model`（`factors.py:53-105`）：全量 YAML 定义（167+），无 IC。
- `GET /api/v1/factors/active`（`factors.py:108-209`）：33 个已注册计算因子，**已返回分类明细**（categories[].factors[].{code,name,subcategory,description,standardization,ic_threshold,ic_value} + valid/warn/no_data_count）。
  - **硬编码**：`factors.py:144-152` 对 3 个 `china.policy.*` 因子在 IC=None 时强置 `ic_val=0.0` → 前端显示"已计算"，**掩盖"从未算过"**。
  - `no_data_count` 由前端从 `ic_value is None` 推导（`:173`），服务端无权威状态。
- `GET /api/v1/factors/ic`（`factors.py:236-278`）：**`abs(val) > 0.0` 过滤**（`:265`）→ china 0 值因子在 /ic 消失，与 /active 不一致；`sample_count` 硬编码 `None`（`:262`）。
- `GET /api/v1/admin/factor-health`（`admin.py:133-162`）：每 symbol {total, live, ratio, healthy}，**无 IC 明细**；`admin.py:144` 新建 `FactorRegistry()`（非单例），不更新 `_last_ic_batch`。
- 状态来源：`factor_registry._last_ic_batch`（`factor_registry.py:669`）仅内存单例，由 `compute()` 更新（`:1147-1150`）——**无时间戳、无样本数**；ic_batch 为空时保持旧值。
- `ic_tracker.compute_periodic_ic`（`ic_tracker.py:126-174`）：返回 `dict[code, float]`，**丢样本数**；`compute_ic`（`:69-85`）样本 <3 返回 **0.0**（"真实 IC=0"与"算不出来"不可区分）。
- 前端：`FactorModelView.vue:118-120` 本地推导状态（`abs(ic)>=threshold ? 有效 : 低于阈值`），`FactorICView.vue:93` 展示 `sample_count ?? '-'`（永远 '-'）。

### 5.2 根因

1. `/active` 名义上暴露了明细，但**状态字段缺失**（无样本数/新鲜度/权威 status+reason），前端只能从 `ic_value` 推导 → "已修但 IC 为 N/A"的困惑。
2. 硬编码 0.0 掩盖未计算状态，且 `/ic` 过滤 0 值导致两端点不一致。
3. IC 数据模型（float dict）不支持样本数与时间戳，无法支撑"分类明细"的完整语义。

### 5.3 修复设计

#### ① IC 数据模型升级（向后兼容）

`factor_registry._last_ic_batch` 结构从 `dict[code, float]` 升级为 `dict[code, dict]`：

```python
_last_ic_batch: dict[str, dict] = {
    code: {"ic": float, "n": int, "ts": float(epoch)},
}
```

- `ic_tracker.compute_periodic_ic` 返回结构同步升级：`{code: {"ic": ic, "n": n_common}}`（`n` 为公共样本数，原 `:167-169` 处已有 n 可透出）。
- **兼容适配**：保留 `_last_ic_batch.get(code)` 返回 `float` 的读取习惯 → 增加辅助 `_ic_value(code)` 返回 `float | None`，所有现有读取点改为经辅助函数读取。**实际读取点（已核查）**：`factors.py:128,254`（/active、/ic）、`main.py:351-356`（落库）、`factor_registry.py:669,1150`（定义/写入）、`ic_tracker.py:193`（注释）——**admin.py 不读单例**（新建实例，见 §5.3③ 一并改为单例）。
- 附带修复：`compute_ic` 样本 <3 返回 0.0 改为返回 `(0.0, 0)`（ic=0, n=0），`n` 作为"未计算"的判据（`n==0 or n<3 → status="insufficient_data"`），消除"真实 IC=0"与"算不出来"混淆。
  - **联动**：`compute_periodic_ic` 现有 `|val|<0.001 跳过`（`ic_tracker.py:156-157`）会把 0 值因子**排除出 ic_batch** → 修复时改为"0 值也入 batch 且带 n"（或服务端对"不在 batch 但有 compute 函数"的因子统一判 `insufficient_data`）。二选一，实施时取其一并保证 `/active` 与 `/ic` 一致。

#### ② 服务端权威状态（移除硬编码）

`/active`（`factors.py:108-209`）每因子新增字段：

```python
{
  "code", "name", "subcategory", "description", "standardization",
  "ic_threshold", "ic_value",
  # 新增：
  "sample_count": int | None,     # 公共样本数（来自 ic_tracker）
  "last_ic_at": str | None,       # ISO 时间戳（_last_ic_batch 的 ts）
  "has_computer": bool,           # 是否注册了 compute 函数
  "status": "valid" | "warn" | "no_data" | "not_computed" | "insufficient_data",
  "reason": str,                  # 中文原因，如 "IC 样本不足(<30)" / "未注册计算函数" / "IC 低于阈值 0.02" / "运行时间不足"
}
```

- **删除** `factors.py:144-152` 硬编码（`china.policy.*` 不再强置 0.0）。
- 状态判定（服务端唯一权威，前端不再推导）：
  - 无 compute 函数 → `not_computed`（YAML 有定义但不在 `_computers`，如大部分 china_specific）
  - 有 compute 但 `n` 缺失或 `n < 3` → `insufficient_data`
  - `ic is None` → `no_data`
  - `abs(ic) >= threshold` → `valid`；否则 `warn`
- 分类聚合保持 valid/warn/no_data_count（按新 status 映射：`not_computed`/`insufficient_data` 计入 no_data 或单独 `not_computed_count`——**设计决定**：新增 `not_computed_count`，前端"待关注"tooltip 显示 reason）。

#### ③ 端点一致性 + 新增汇总

- `/ic`（`factors.py:236-278`）：移除 `abs(val) > 0.0` 过滤（保留 0 值因子，与 /active 一致），`sample_count` 用真实 `n`。
- `/active` 与 `/ic` 共用同一辅助函数读 `_last_ic_batch`，保证一致。
- 新增 `GET /api/v1/factors/categories`（可选，若前端需要轻量汇总）：返回 `[{category, count, valid_count, warn_count, no_data_count, not_computed_count, avg_ic, updated_at}]`——与 `/active` 的 categories 头部同构（可直接复用现有构建逻辑）。
- `admin factor-health`：每 symbol 明细增加 IC 摘要（`avg_ic`、`filled_count`），且**使用单例 registry**（`from ..factors.factor_registry import registry`），移除 `admin.py:144` 新建实例。
  - 安全性：单例 `compute()` 仅当传入 `market_data` 时才更新 `_last_ic_batch`（`factor_registry.py:1147-1150`）；admin 的 `fr.compute(symbols)` 不传 market_data → **不会污染** `/active` 的 IC 状态，可放心切单例。

#### ④ 前端适配

- `FactorModelView.vue:118-120`：移除本地推导，直接用 `f.status`/`f.reason` 渲染（"待关注" tooltip 显示 `reason`，见 v5.1 的 UX 设计章节）。
- `FactorICView.vue:93`：`sample_count` 展示真实值。

### 5.4 验收标准

- **单测**（`backend/tests/test_factor_status.py`）：
  1. 无 compute 的 china 因子（如 `china.soe.*`）→ `/active` 中 `status == "not_computed"`、`ic_value is None`（**不再是 0.0**）。
  2. `_last_ic_batch` 升级后，`/active` 与 `/ic` 对同一因子的 ic_value 一致（0 值因子两边都在）。
  3. mock `ic_tracker` 返回 `{code: {"ic": 0.05, "n": 40}}` → status=valid；`{"ic": 0.01, "n": 40}` → warn；`n=2` → insufficient_data。
  4. `sample_count`/`last_ic_at` 字段存在且类型正确。
- **verify_e2e**（`section_factor_ic` 增强）：断言 `/factors/active` 返回的每个 factor 含 `status`/`reason` 字段（契约形态）；断言 `/factors/ic` 与 `/factors/active` 无矛盾（同 code 同 ic_value）。
- **契约**：`api-contracts/factors/active.md`（如存在）或 `api-contracts/factors/registry.md` 更新响应结构。

---

## 6. Z11 — 非交易时段设计失败（无法复现/无法自动验证）

### 6.1 现状与证据

- 链路：`design_tasks.py`（re-export 兼容层）→ `strategy_design.generate_enhanced_design`（`strategy_design.py:21-99`）：
  - `refresh()`（`:40`）→ `get_factor_matrix() or {}`（`:51-54`）→ `get_pool(...)`（`:55-59`）→ 空池检查（`:61-78`）→ `engine_allocate`（`:93-98`）。
- **三层静态兜底互不契约**：
  - **A**（`strategy_design.py:65-72`）：空池 → 硬编码 6 只 ETF；`getattr(market_data_hub, "etf_pool", None)` **恒为 None**（hub 无此属性，死代码）→ 永远走硬编码列表。
  - **B**（`strategy_design.py:185-236`）：异常兜底 → 固定 1 套 `id:"balanced"` 静态策略，`design_metadata.fallback=True`。
  - **C**（`allocation_engine.py:87-102`）：`_DEFAULT_CANDIDATES` 11 只，与 A 的 6 只**部分重叠**（510300/518880/511090 两处重复），560600/512890/513500 等 8 只仅存在于 C。
- **非交易时段实际行为**：`get_pool` 空 → A 路径：`factor_matrix={}` + 6 只静态候选 → `_select_and_weight` 中 `factor_score = factor_matrix.get(sym,{}).get("technical",0)=0`（`allocation_engine.py:159`）→ 全零分 → `_power_law_weights` 均匀分配 → **"设计成功但退化为均匀权重"**，且 `design_metadata.fallback` 为 False（用户无感知）。
- 测试现状：`backend/tests/test_strategy_design.py:8-35`（mock 空池+空矩阵 → 断言 3 套）；`backend/tests/test_design_cascade_failure.py:37-51`（mock 全部 hub 方法 → 断言 strategies>0）。**无"池非空但 factor_matrix 空"场景**（最常见的非交易时段形态：ETF 池来自本地静态文件、因子矩阵需要实时数据）；verify_e2e 纯 HTTP 冒烟，无法模拟数据不足。

### 6.2 根因

1. 三条降级路径产出**不同形状**的结果（3 套均匀权重 / 1 套静态 / 引擎 11 只池），且 A 路径无 fallback 标识 → 降级不可观测、不可断言。
2. `etf_pool` 属性不存在（设计未落地），静态池位置混乱（两处硬编码不重叠）。
3. "池非空但 factor_matrix 空"（数据部分可用）场景静默产生均匀权重，比抛错更隐蔽。

### 6.3 修复设计

#### ① 统一静态候选池（单一来源）

新增 `backend/app/engine/static_pool.py`：

```python
STATIC_CANDIDATES: list[dict] = [
    # 合并现有 A（strategy_design.py:66-71，6 只）与 C（allocation_engine.py:87-102，11 只）两处硬编码，
    # 按 symbol 去重（510300/518880/511090 两处重复），保留 layer 字段 → 共 14 只
    {"symbol": "510300", "name": "沪深300ETF", "market": "A", "layer": "core"},
    {"symbol": "510050", "name": "上证50ETF", "market": "A", "layer": "core"},
    {"symbol": "518880", "name": "黄金ETF", "market": "A", "layer": "defense"},
    ...  # 全部从两处现列表合并去重
]
STATIC_REGIME = "range_bound"
```

- `strategy_design.py:65-72`：`getattr(market_data_hub, "etf_pool", None)` 死代码删除，空池时直接用 `STATIC_CANDIDATES`，并设置 `fallback=True, fallback_reason="candidate_pool_empty"`。
- `allocation_engine.py:87-102`：`_DEFAULT_CANDIDATES` 改为 `from .static_pool import STATIC_CANDIDATES`（消除两处不一致）。

#### ② 降级形态契约（所有降级路径可观测、形态一致）

- `generate_enhanced_design` 返回的 `design_metadata` 增加契约字段（`strategy_design.py:185-236` 与 A 路径统一）：
  ```python
  design_metadata = {
      ...现有字段...,
      "fallback": bool,            # 任何降级路径均为 True
      "fallback_reason": str | None,  # "candidate_pool_empty" | "factor_matrix_empty" | "engine_error" | None
      "data_quality": {"pool_count": int, "factor_matrix_size": int},
  }
  ```
- **数据分级判定**（`strategy_design.py:49-78` 新增辅助 `_assess_data_quality(...)`）：
  - 池空 + 矩阵空 → `candidate_pool_empty`，用 STATIC_CANDIDATES + **STATIC 权重**（预设层权重，非均匀——见 ③）。
  - 池非空 + 矩阵空（**最常见非交易时段形态**）→ `factor_matrix_empty`：**不再静默均匀权重**，改为用静态层权重作为因子缺失时的默认分（`allocation_engine.py:159` 的 `factor_score = 0` 处，改为 `factor_matrix.get(sym, {}).get(...) or static_pool 默认分`），输出 3 套方案且 `fallback=True`。
  - 矩阵部分缺失（部分标的无因子）→ 正常路径 + 现有 `data_quality` 注记（不标 fallback）。
- `allocation_engine._power_law_weights` 当全零分时改用**静态层预算权重**——**直接引用 `STRATEGY_META[risk_profile]["layer_budget"]`**（如 balanced: core 0.40 / satellite 0.30 / defense 0.10，`budgets.py`），层内按候选数均分；**避免"均匀权重"这种伪正常输出**，且不引入与 STRATEGY_META 不一致的拍脑袋比例（0.4/0.35/0.25 之类废弃）。
  - 注意保留 `MANDATORY_CODES`/`MANDATORY_MIN_WEIGHT` 语义（`allocation_engine.py:83-84`，强制 510300/560600/518880/511090 ≥3%），降级路径同样适用。

#### ③ 可验证性（关键：让"非交易时段"可自动验证）

- **单测**（`test_strategy_design.py` 扩展 + 新增 `test_design_degraded.py`）：
  1. mock `get_pool` 返回空 + `get_factor_matrix` 返回 `{}` → 断言 3 套方案 + `design_metadata.fallback=True` + `fallback_reason="candidate_pool_empty"` + 权重非均匀（有层间区分）。
  2. **新增场景**：mock `get_pool` 返回非空（如 3 只）+ `get_factor_matrix` 返回 `{}` → 断言 `fallback_reason="factor_matrix_empty"` + 权重非均匀。
  3. mock `engine_allocate` 抛异常 → 断言 B 路径 `fallback=True` 且形态与 A 一致（3 套，而非 1 套——**设计决策**：B 路径也输出 3 套静态方案，用 STRATEGY_META 的 3 个风险档位）。
  4. 断言 `STATIC_CANDIDATES` 与两处旧硬编码无遗漏（去重后数量/符号集合与预期一致）。
- **verify_e2e**（`section_async_resilience` 或 `section_solution_diversity_check` 增强）：
  1. 设计完成后 `GET /designs/{id}`：断言 `design_metadata` 含 `fallback`/`fallback_reason` 字段（结构契约）。
  2. **弱断言**：当 `fallback==true` 时 3 套方案层权重存在区分（`allocation_engine` 输出各层平均权重不等），防止均匀权重回归。
  3. 可选测试钩子（P2）：`GET /design/dry-run?degrade=1` 强制走降级路径（仅测试用，标注 non-production），使 verify_e2e 可稳定复现非交易时段行为。**设计决策**：优先用单测覆盖（确定性），dry-run 钩子作为补充，避免生产 API 暴露测试路径。

### 6.4 验收标准

- 单测 4 个场景全过（覆盖三层兜底 + 最常见部分数据场景）。
- verify_e2e design 模块增加 fallback 元数据断言。
- **定义明确**：非交易时段（任何数据缺失形态）不再出现"成功但均匀权重"的静默输出。

---

## 7. Z20 — 搜索排序不透明（UX / 无法自动验证）

### 7.1 现状与证据

- 端点与实现（全部 **ILIKE + LIMIT，无 ORDER BY**）：
  - `GET /api/v1/market/search`（`market.py:61-113`）：A 股查 instruments 四字段 ILIKE + LIMIT 30（`:79-89`）；HK/US 走 `search_hk_us`（`:108-111`）。
  - `market_service.search_etf`（`:531-576`）：同 ILIKE + LIMIT 30；akshare 降级按 symbol/name 包含过滤取前 20（**列表原始顺序**）。
  - `search_hk_us`（`:608-638`）：静态表过滤，**保持表序**。
  - `search_indices`（`:698-728`）：ILIKE + LIMIT 50。
- 数据：`instruments` 表含 `pinyin`（全拼）、`first_letter`（首字母）字段（`models/search.py:15-27`，均有索引）；`sync_indices_meta.py` 用 `pypinyin` 生成。
- 前端：`PortfolioManager.vue:517-523`、`WatchlistPanel.vue:231-239` `slice(0,10)` 原样渲染，无排序。
- 可验证性缺口：无 ORDER BY → 顺序依赖 SQLite 查询计划/主键扫描，**同一查询在不同时刻可能不同序**，任何"看起来 OK"的手动验证不可复现。

### 7.2 根因

排序契约缺失：搜索返回顺序未定义，导致 (a) UX 不稳定（同样输入不同序），(b) 无法自动化断言。

### 7.3 修复设计

#### ① 统一分档排序契约（后端所有搜索路径）

排序优先级（**所有搜索路径共用**）：

```
rank 0: symbol == kw                （精确代码）
rank 1: symbol.startswith(kw)       （代码前缀）
rank 2: name.startswith(kw)         （名称前缀）
rank 3: kw in name                  （名称包含）
rank 4: pinyin.startswith(kw)       （拼音前缀）
rank 5: first_letter.startswith(kw) （首字母前缀）
rank 6: kw in symbol                （代码包含，兜底）
同 rank 内：按 len(name) 升序 → symbol 字典序（确定性）
```

- **SQL 路径**（`search_etf`/`search_indices`/`/search` A 股分支）：`ORDER BY` 用 CASE WHEN 表达式：
  ```sql
  ORDER BY
    CASE WHEN symbol = :kw THEN 0
         WHEN symbol LIKE :kw_prefix THEN 1
         WHEN name LIKE :kw_prefix THEN 2
         WHEN name LIKE :kw_contains THEN 3
         WHEN pinyin LIKE :kw_prefix THEN 4
         WHEN first_letter LIKE :kw_prefix THEN 5
         ELSE 6 END,
    length(name), symbol
  ```
  （kw 均先 `lower()`，与现有 `ilike` 语义一致；SQLite 的 CASE 支持如上写法。注意 SQLite `LIKE` 对 ASCII 默认大小写不敏感，与 `ilike` 一致，无需额外 lower() 处理；若用显式 `lower(column) LIKE lower(:kw)` 亦可，二选一保持一致。）
- **Python 降级路径**（akshare/levistock 全量过滤、`search_hk_us` 静态表、`/search/stocks` 降级）：过滤后用同一 `_sort_key(item, kw)` 排序（新增 `market_service._search_sort_key` 纯函数，供单测直接调用）。
- `search_hk_us` 静态表：同样套用排序（name 前缀优先）。
- **统一入口**：建议把排序逻辑收敛为 `market_service.py` 中两个辅助：`_build_search_order_clause(kw)`（SQL 片段）与 `_sort_results(results, kw)`（Python）。所有路径调用之，避免各写各的。

#### ② 个股搜索补强（与 Z22 联动）

- 现状：`/search/stocks` DB 路径恒空（instruments 无 stock 行）→ 前端 `/search` 搜不到个股（只能靠 `/search/stocks` 且走全量降级）。
- 设计（P1 可选，纳入本期）：
  - **A（推荐，改动小）**：`GET /api/v1/market/search`（`market.py:61-113`）在**默认分支**（无 `market` 参数，`:113` 走 `search_etf`）返回空时，降级调用 `get_all_stocks` 名称匹配（复用 Z20 排序契约），使个股可被搜到；`/search/stocks` 的 DB 路径顺带修复——若 instruments 同步了个股则直接走索引，否则降级全量。
  - B（P2，涉及调度任务）：`sync_instruments`（`scripts/run_scheduler.py` 每日调度）扩展同步 A 股个股 → instruments 增加 `asset_type='stock'` 行，`/search/stocks` DB 路径可用、Z22 名称反查也可走索引。
  - **决策**：本期做 A（无结果降级 + 名称匹配），B 作为 P2（涉及调度任务改动，收益与风险比低）。

#### ③ 前端

- `PortfolioManager.vue:517-523`、`WatchlistPanel.vue:231-239`：**依赖后端排序**，`slice(0,10)` 保留（排序已完成），或改为展示后端返回的完整前 10 条；不做前端二次排序（避免双端契约漂移）。

### 7.4 验收标准

- **单测**（`backend/tests/test_search_sort.py`）：
  1. `_sort_key` 纯函数：给定混合结果集（精确/前缀/包含/拼音），断言排序档位符合契约。
  2. SQL 路径（mock session）：断言生成的 `ORDER BY` 含 CASE 分档（或直接集成断言：`search_etf("300")` 返回中 `510300` 排名先于 `300ETF` 类名称匹配……具体断言用 mock 行构造）。
  3. `search_hk_us("QQ")` → QQQ 排第一（名称前缀优先于其他）。
- **verify_e2e**（`section_search` 增强）：
  1. `GET /market/search?keyword=510300` → 结果[0].symbol == "510300"（精确代码第一）。
  2. `GET /market/search?keyword=300` → 断言"代码前缀命中"排在"名称包含命中"之前（构造稳定断言：取返回前 3 条，断言不存在"name 包含但 symbol 不含 300 前缀且排在前"的反例——即按契约校验顺序）。
  3. 弱断言：连续两次同 keyword 请求，返回 symbol 序列一致（确定性回归哨兵）。

---

## 8. 测试与验收汇总

| 问题 | 单测文件（新增/扩展） | verify_e2e 增强 | 契约文件更新 |
|------|----------------------|-----------------|-------------|
| Z22 | `test_watchlist_dirty.py` | `section_watchlist`（新） | `api-contracts/market/watchlist.md` |
| Z25 | `test_stock_hot_rank.py` | `section_market`（stock-hot-rank 字段） | `api-contracts/market/hot-plates.md` |
| Z26 | `test_strategy_check_coverage.py` | `section_portfolio`/`section_async_resilience` | `api-contracts/portfolio/strategy-check-report.md` |
| Z05 | `test_fund_nav_session.py`（NAV 直连） | 预热日志 ssl_handshakes 哨兵 | `api-contracts/system/warmup.md`（验收口径） |
| Z03 | `test_factor_status.py` | `section_factor_ic` | `api-contracts/factors/registry.md`（或 active.md） |
| Z11 | `test_strategy_design.py` 扩展 + `test_design_degraded.py` | `section_solution_diversity_check` | `api-contracts/portfolio/design-enhanced.md`（design_metadata） |
| Z20 | `test_search_sort.py` | `section_search` | `api-contracts/market/search.md` |

共性要求（项目 AGENTS.md 强制流程）：
1. **契约先行**：每个问题先更新 `api-contracts/` 对应文件，再编码。
2. **单测必须 mock 外部依赖**（akshare/levistock/DeepSeek/网络），不依赖真实 DB/网络。
3. 后端改完必须 `python -m pytest` 全绿 + `python scripts/verify_e2e.py` 全 PASS 才能 commit。
4. 前端改动 `npm run build` 无编译错误。

---

## 9. 实施顺序与工作量估算

| 优先级 | 问题 | 工作量 | 理由 |
|--------|------|--------|------|
| P0 | Z26 规则兜底 | 0.5~1 日 | 核心功能可靠性，LLM 超时即空报告是高风险 |
| P0 | Z22 写入校验 + 读取自愈 | 0.5~1 日 | 用户可见数据残缺，且自愈是一次性修复历史数据 |
| P1 | Z25 volume/sector 补全 | 0.5 日 | 数据完整性，改动集中在 sector_fetcher |
| P1 | Z05 NAV 直连 + 验收口径 | 0.5~1 日 | 预热性能 + 验收可测化 |
| P1 | Z03 服务端状态 | 0.5~1 日 | 需要适配 _last_ic_batch 全部读取点（改动面中） |
| P2 | Z11 降级契约 | 0.5 日 | 测试驱动，纯后端 |
| P2 | Z20 排序契约 | 0.5 日 | 纯后端 + verify_e2e 断言 |
| P3 | 前端展示（Z25 volume/sector 列、Z03 tooltip、Z22 提示） | 0.5 日 | 依赖后端契约落地 |

依赖关系：
- Z22 的读取自愈依赖 `get_all_stocks` 全量 A 股可用（已存在，无新依赖）；可选依赖 Z20 的搜索排序（名称反查可复用排序后的匹配顺序）。
- Z26 规则兜底与 Z09（sigma 异常）有交互——σ 值异常大时阈值判断仍成立（±1.5σ 门槛在 25σ 下同样触发 increase/decrease），规则需对极端 σ 做截断（如 `min(max(σ,-3),3)` 再判阈值），在设计中已隐含，实施时在 `build_rule_suggestions` 中显式处理。
- Z11 与 Z04（etf_specific 因子数据管道）相关：Z04 修复后 factor_matrix 覆盖提升，非交易时段场景仍然存在（静态池 + 空矩阵），本设计不依赖 Z04。

---

## 10. 风险与边界

1. **Z22 回写唯一约束**：symbol unique 冲突时放弃回写，仅本次响应有效；不引入数据迁移脚本（脏数据量小，读取时自愈足够；如后续量大可加一次性迁移脚本，本期不做）。
2. **Z25 外部库耦合**：levistock 包内字段不可改；所有补全在 repo 侧，levistock 升级不影响；东财 clist f100 字段若被风控/改版，sector 为 null（可接受降级）。
3. **Z26 规则阈值**：±1.5σ 与 drift>20% 为 v1 经验值，实施后按真实数据校准；规则输出不替代 LLM 深度分析，只保证覆盖兜底。
4. **Z05 验收口径变化**：需在文档/契约中明示"绝对 <5"不可达的原因（akshare 内部不可注入），改为 per-host ≤1 + 总握手 ≤（可控 host 数 + 1，实测约 ≤8）的量化口径，并实测校准。
5. **Z03 数据模型升级**：`_last_ic_batch` 结构变化影响的**实际读取点**（已核查）：`factors.py:128,254`（/active、/ic）、`main.py:351`（落库）、`factor_registry.py:669,1150`（定义/写入）、`ic_tracker.py:193`（注释）——**admin.py 不读单例**（它新建实例），无需适配；实施时逐点适配并跑全量单测；若担心回归，可先加兼容读函数（`_ic_value`）再迁移。
6. **Z11 静态池合并**：A/C 两处硬编码合并后，引擎行为变化（候选池从 11 只变 14 只，且 strategy_design 空池兜底从 6 只变 14 只），需跑现有相关用例确认无回归——**注意 `backend/tests/` 下没有 `test_allocation_engine.py`**，相关覆盖在 `test_design_optimization_plan.py`（P0-P3 用例）、`test_pool_manager*.py`、`test_risk_controls.py`、`test_design_*.py` 中；实施时先跑这些套件，并**新增** `test_static_pool.py` 断言合并后符号集合与层分布。
7. **Z20 SQL CASE**：SQLite 支持 CASE 表达式；`ilike` 与 `LIKE lower()` 混用注意大小写一致性（统一 `lower()` 比较）。

---

## 11. Review 记录

| 轮次 | 审查人 | 日期 | 结论 | 修改要点 |
|------|--------|------|------|---------|
| R0 | 自审（设计初稿） | 2026-07-31 | 初稿完成，659 行 | - |
| R1 | 自审 | 2026-07-31 | 6 处修正 | Z22 删"批量重试第三层"含糊步骤/名称匹配复用 Z20 排序；Z26 engine 层不得依赖 services（confidence 由调用方回填）；Z11 静态池"部分重叠"修正（6∪11=14 只去重）；Z05 验收口径改为"可控 host+1（≈≤8）"并补并发说明；Z03 补 ic_tracker 0 值跳过联动 + admin 单例安全说明；Z20 补 SQLite LIKE 大小写说明 |
| R2 | 独立审查（实测验证） | 2026-07-31 | 6 处修正（1 处 MAJOR） | **MAJOR**：Z26 规则输出 action 枚举 BUY/SELL/HOLD 与 `strategy_check.md` 契约（increase/decrease/hold）不一致 → 已改为契约对齐并补 current_weight/suggested_weight 规则；**其余**：Z26 合并位置明确到 `portfolio_service.py:500`（LLM 兜底之后、P2-1 回填之前）；Z11 静态层权重改引用 `STRATEGY_META.layer_budget`（废弃 0.4/0.35/0.25 拍脑袋值）+ 保留 MANDATORY_CODES 语义；Z11 风险引用修正（无 test_allocation_engine.py，实际套件列出 + 新增 test_static_pool.py）；Z03 读取点修正（admin.py 实非读取点，实测 5 处）；Z20 个股降级明确方案 A/B 与决策 |
| R3 | 最终通读（一致性） | 2026-07-31 | 3 处 NIT 修正 | Z22 伪代码删除残留"批量重试第三层"分支（与 R1 决策一致）；Z26 prompt 文案 BUY/SELL/HOLD → increase/decrease/hold；Z03 §5.3① 适配点列表与 §10 对齐；依赖关系措辞同步 |

（每轮 review 后更新本表与正文。）

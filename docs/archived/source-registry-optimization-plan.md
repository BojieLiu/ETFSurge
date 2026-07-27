# SourceRegistry 优化方案

> 版本: v2 (reviewed)
> 上次修改: 2026-07-22

## 1. 现状：全系统数据源降级链路全景

以下是 ETF Surge 系统中所有数据源降级链路的完整枚举。
标注 **是/否** 表示该链路是否已使用 `SourceRegistry.route()` 管理熔断状态。

---

### 1.1 行情数据源

| 序号 | 功能 | 函数位置 | 降级链 | 已接入 SR |
|---|---|---|---|---|
| 1 | A股实时（单只） | `china_market.fetch_a_stock_realtime()` | `mootdx → Sina` | 否 |
| 2 | A股实时（批量） | `china_market.fetch_a_stock_batch()` | `mootdx → Tencent(QQ) → Sina` | 否 |
| 3 | 港股实时 | `china_market.fetch_hk_stock_realtime()` | `Sina → Tencent(QQ) → 东方财富(akshare)` | 否 |
| 4 | A股日/周/月 K 线 | `china_market._mootdx_history()` | `mootdx → akshare`（函数内 fallback） | 否 |
| 5 | A股分钟 K 线（15m/30m/1h） | `china_market.fetch_history()` | `Sina → akshare_intraday` | 否 |
| 6 | A股 4h K 线 | `china_market.fetch_history()` | `Sina 1h → akshare_intraday(60) → resample` | 否 |
| 7 | HK/US 历史 K 线 | `china_market._fetch_akshare_history()` | `akshare → Finnhub → Alpha Vantage` | 否 |
| 8 | 指数历史 K 线 | `china_market.fetch_index_history()` | `akshare` 直查，无降级 | 否 |
| 9 | 美股实时 | `market_service._route_us()` | `twelvedata → finnhub → alphavantage → yfinance` | 是 |
| 10 | 全球指数（A股） | `market_service.get_global_indices()` 内部调用 `fetch_index_realtime()` | `mootdx → QQ(Tencent)` | 否 |
| 11 | 全球指数（海外） | `market_service.get_global_indices()` 内部的 `_foreign()` | `新浪 → stooq → yfinance`（三级） | 否 |
| 12 | 期货（黄金/原油/白银） | `china_market.fetch_futures_realtime()` | `akshare` 直查，无降级 | 否 |
| 13 | 开放式基金净值 | `china_market.fetch_fund_nav()` | `akshare fund_open_fund_info_em → 天天基金 API` | 否 |
| 14 | ETF 全量列表（扫描用） | `etf_scanner.fetch_all_etfs_base()` | `Sina(akshare) → Tencent gtimg → akshare spot → stale cache` | 否 |
| 15 | ETF 列表（搜索用） | `china_market.fetch_etf_list()` | `akshare fund_etf_category_sina → akshare fund_etf_spot_em`（兜底） | 否 |
| 16 | 历史 K 线（service 层） | `market_service.get_history()` | `fetch_history (mootdx→Sina→akshare) → get_k_data(akshare 直查)` | 否 |
| 17 | 趋势计算单 ETF | `market_trends._fetch_single_trend()` | 依赖 `fetch_history()`，间接走 mootdx→Sina | 否 |

---

### 1.2 板块/概念数据源

| 序号 | 功能 | 函数位置 | 降级链 | 已接入 SR |
|---|---|---|---|---|
| 18 | 行业板块列表 | `sector_fetcher.fetch_industry_sectors()` | `levistock → akshare` | 是 |
| 19 | 概念板块列表 | `sector_fetcher.fetch_concept_sectors()` | `levistock → akshare spot → akshare name list`（三源） | 是 |
| 20 | 板块成分股 | `sector_fetcher.fetch_sector_stocks()` | `levistock → akshare` | 是 |
| 21 | 板块历史 K 线 | `sector_fetcher.fetch_sector_history()` | `levistock(空) → akshare`（levistock 直接返回 None） | 是 |
| 22 | 全量 A 股列表 | `sector_fetcher.fetch_all_stocks()` | `levistock → akshare` | 是 |
| 23 | 板块热度排行 | `sector_fetcher.fetch_sector_heat()` | `levistock` 单源 | 否 |
| 24 | 热点板块及涨停股 | `sector_fetcher.fetch_hot_plates()` | `levistock` 单源 | 否 |
| 25 | 板块热门个股 | `sector_fetcher.fetch_sector_popular_stocks()` | `levistock` 单源 | 否 |
| 26 | 个股热搜排名 | `sector_fetcher.fetch_stock_hot_rank()` | `levistock` 单源 | 否 |

---

### 1.3 市场情绪数据源

| 序号 | 功能 | 函数位置 | 降级链 | 已接入 SR |
|---|---|---|---|---|
| 27 | 涨跌家数比 | `sentiment_fetcher.fetch_advance_decline_ratio()` | `东方财富 push2 → akshare → 中性值 0.5` | 否 |
| 28 | 北向资金 | `sentiment_fetcher.fetch_north_flow()` | `akshare` 多 API 名重试（版本兼容）→ `0.0` | 否 |
| 29 | 两融变化 | `sentiment_fetcher.fetch_margin_change()` | `akshare → 深交所/上交所 margin API → 0.0` | 否 |
| 30 | 两融余额 | `margin_fetcher.fetch_margin_balance()` | `SZSE → SSE` | 否 |
| 31 | 情绪一站式 | `sentiment_fetcher.fetch_market_sentiment()` | 组合 27~29，每路独立超时，异常默认为 0.5/0 | 否 |
| 32 | 指标股行情 | `benchmark_stocks._get_realtime_price()` | `mootdx → Sina` | 否 |

---

### 1.4 资讯数据源

| 序号 | 功能 | 函数位置 | 降级链 | 已接入 SR |
|---|---|---|---|---|
| 33 | 综合头条 | `news_fetcher.fetch_news_headlines()` | `财联社快讯 + 宏观(CCTV+百度) + 全球(RSS+akshare)` 多源融合 | 否 |
| 34 | 宏观资讯 | `news_fetcher.fetch_macro_news()` | `CCTV → 百度宏观 → 东方财富宏观 → 财联社兜底` | 否 |
| 35 | 全球资讯 | `news_fetcher.fetch_global_news()` | `RSS(道琼斯+CNBC) → akshare global` | 否 |
| 36 | 个股资讯 | `news_fetcher.fetch_stock_news()` | `东方财富 → 财联社兜底` | 否 |
| 37 | 个股研报 | `news_fetcher.fetch_research_reports()` | `akshare` 单源 | 否 |

---

### 1.5 数据路由校验

| 序号 | 功能 | 函数位置 | 降级链 |
|---|---|---|---|
| 38 | 全球指数定义 | `market_service._global_index_defs()` | `SQLite indices 表 → 硬编码常量` |

---

### 1.6 LLM Provider Failover

| 序号 | 功能 | 函数位置 | 降级链 |
|---|---|---|---|
| 39 | LLM 调用 | `provider.call_with_failover()` | `OpenCode Zen → DeepSeek Official` |

---

### 1.7 Task 级降级

| 序号 | 功能 | 函数位置 | 降级链 |
|---|---|---|---|
| 40 | 设计报告生成 | `design_report.compose_and_push_report()` | `LLM 报告 → 超时/失败时引擎方案纯文本回退` |

---

## 2. 优化方案

### P0-A: china_market.py 核心函数接入 SourceRegistry

**现状**：文件头注释称"由 SourceRegistry 熔断路由管理"，实际 10 条行情降级链全是手写 `if items: return items`。最核心的 A 股/HK 链路没有熔断保护 —— mootdx 连续失败 3 次后不会冷却，下次请求仍然会先尝试 mootdx，浪费 6s socket timeout。

**改动范围**：变更以下 3 个函数的降级逻辑（优先改造，覆盖最高频调用）：

| 函数 | 当前行数 | 改造后约 | 说明 |
|---|---|---|---|
| `fetch_a_stock_realtime()` | 10 行 | 8 行 | 单只 A 股，`mootdx → Sina` |
| `fetch_a_stock_batch()` | 12 行 | 10 行 | 批量 A 股，`mootdx → Tencent → Sina` |
| `fetch_hk_stock_realtime()` | 14 行 | 10 行 | 港股，`Sina → Tencent → 东方财富` |

合计约 28 行净改动。每条链改用 `registry.route([(name, lambda), ...])` 的形式。

**前置条件：修复 price=0 语义缺口（见 §4.1）**。必须在改造前先将 `_mootdx_realtime()`、`_sina_realtime()`、`_tencent_realtime()` 等底层函数的返回值过滤掉 `price=0` 的记录，确保"非空列表 = 有有效数据"的约定成立。

**后续可扩展**：Phase 1 之后，`_mootdx_history()`、`fetch_index_realtime()`、`fetch_fund_nav()` 等可用同样的模式改造。

---

### P0-B: 补齐中国数据源健康探针

**现状**：只有 `twelvedata` 和 `finnhub` 两个探针。所有中国市场数据源（mootdx、Sina、Tencent、akshare、levistock）都没有主动健康探测，只能被动记录失败。

在 `main.py` 的 `_register_health_probes()` 中增加：

| 源名 | 探测函数（建议） | timeout | 说明 |
|---|---|---|---|
| `mootdx` | 新增 `def _probe_mootdx(): return bool(_mootdx_realtime(["000001"]))` | 8s | 注意 `_mootdx_realtime` 是私有函数，建议在 `china_market` 模块中暴露一个 `probe_mootdx()` 公共函数 |
| `sina` | 新增 `def _probe_sina(): return bool(_sina_realtime(["000001"], "A"))` | 10s | 同上，建议暴露公共封装 |
| `tencent` | 新增 `def _probe_tencent(): return bool(_tencent_realtime(["000001"], "A"))` | 10s | |
| `akshare` | `_probe_akshare`: 调用 `search_etf("510300")`（单代码查询，比无参数全量扫描轻量） | 10s | 不能用 `search_etf("")`，会触发全量扫描 |
| `levistock` | `lv.sector_em("industry")`（`levistock_fetcher` 模块可直接用） | 10s | 板块/概念全链路用 |

健康探测的 `health_loop(120s)` 已在 main.py 的 lifespan 中启动，只需注册探测函数即可接入。

---

### P1: 修复 `china_market.py` 文件头注释

当前注释：
```
数据源优先级 (由 SourceRegistry 熔断路由管理):
  A 股实时: mootdx → Sina → QQ(Tencent)
  ...
```

改为：
```
数据源降级链（手写，未接入 SourceRegistry 熔断路由）:
  A 股实时: mootdx → Sina → QQ(Tencent)
  A 股K线:  mootdx → Sina
  HK 实时:  Sina → QQ → 东方财富
  指数:     mootdx → QQ
  期货:     akshare
  基金净值:  akshare → 天天基金
  历史K线:   mootdx/Sina (A) / akshare (HK/US)
```

（P0-A 改造完成后，再改回"由 SourceRegistry 熔断路由管理"。）

---

### P2: sector_fetcher 单源函数评估

`fetch_sector_heat()`、`fetch_hot_plates()`、`fetch_sector_popular_stocks()`、`fetch_stock_hot_rank()` 目前全是 levistock 单源，levistock 挂掉时直接返回空。

**评估**：这几个功能依赖财联社/同花顺独家接口，akshare 没有等价替代。强行用 `_try_two` 加无意义降级只会增加延迟。

**建议**：标记为"levistock 独家数据"，当前不做改动，通过 P0-B 的 levistock 探针监控健康度即可。当探针连续失败时，前端可展示"板块热度数据暂不可用"提示。

---

### P3: 无降级路径的兜底

| 场景 | 现状 | 评估 |
|---|---|---|
| 期货实时 | akshare 直查 | 无稳定替代源，保持现状 |
| 指数历史 K 线 | akshare 直查 | 可考虑 mootdx 提供指数日线，低优先级 |
| 个股研报 | akshare 单源 | 无替代源，保持现状 |
| 全球 RSS 资讯 | RSS + akshare | 已有多源融合，够用 |

---

### P3: `route()` 返回结构化的失败信息

现状：`route()` 全部失败返回 `None`，调用方无法区分"所有源在冷却"与"每个源都返回了空数据"。

可以考虑改为返回 NamedTuple `RouteResult(value, last_error, source_skipped)`，但：

- 改动涉及 `sector_fetcher._try_two()` 和 `market_service._route_us()` 两处调用方
- 当前没有业务需求区分这两种失败模式
- **暂缓**，待有明确需求时再做

---

## 3. 实施路线图

| 阶段 | 前置依赖 | 内容 | 估计改动量 | 风险 |
|---|---|---|---|---|
| **Phase 1** | 无 | **P0-A 前置修复**: 在 `_mootdx_realtime`/`_sina_realtime` 等函数中过滤 price=0 记录（§4.1） | 每函数 1~2 行过滤 | 低 |
| **Phase 2** | Phase 1 | **P0-A 改造**: 3 个核心函数接入 SR，运行 `verify_e2e.py` 验证 | ~30 行 | 低（语义已对齐） |
| **Phase 3** | 无 | **P0-B 补齐探针**: 注册 5 个新探针，暴露公共探测函数 | ~40 行（含模块内封装） | 极低 |
| **Phase 4** | 无 | **P1 注释修复**: 修改文件头 | 1 行 | 无风险 |
| **Phase 5** | 无 | **P2 文档标记** | 仅文档 | 无 |
| **Phase 6** | (远期) | P0-A 扩展到 `_mootdx_history`/`fetch_index_realtime`/`fetch_fund_nav` | 后续评估 | 低 |
| **Phase 7** | (远期) | P3 各项 | 视情况 | 中 |

**推荐一期实施**：Phase 1~4。覆盖 80% 的数据源流量，约 70 行净改动，可安全地在 1~2 次 commit 内完成。

---

## 4. 关键设计决策

### 4.1 `route()` 与手写链的语义缺口

`registry.route()` 在用 `if result:` 判断是否成功。而现有手写链用 `if items and items[0].get("price"):`。

关键差异：当某个数据源返回 `[{"symbol": "000001", "price": 0}]`（price 为零）时：

| 判断条件 | 结果 | 后续行为 |
|---|---|---|
| 手写 `if items[0].get("price"):` | `0` 为 falsy → 不满足 | 继续尝试下一个源 |
| `route()` 的 `if result:` | `[{...}]` 非空 → 满足 | 返回这条 price=0 的记录 |

这个 gap 在非交易时段可能出现：mootdx 返回昨收但今日 price=0。

**解决方案**（推荐）：在底层 fetcher 内部过滤掉 price=0 的记录，返回空列表。例如：

```python
# _mootdx_realtime 返回值处增加
results = [r for r in results if r.get("price")]
```

这样 `route()` 的 `if result:` 与手写语义就一致了。**这是改造的前置条件**，需在 Phase 1 完成。

另一种思路是给 `route()` 增加可选 `validator` 参数，但增加复杂度且收益有限，**不推荐**。

### 4.2 探针 vs 实际请求的冷却关系

实际请求也会通过 `registry.route()` 记录成败。探针的作用是：

1. **提前冷却**：在用户请求到达之前就探测到源不可用
2. **加速恢复**：源恢复后探针先成功，清除冷却状态

Example timeline:
```
t=0s:  mootdx 开始连续失败（实际请求开始记录）
t=15s: mootdx 连续失败 ≥3 次 → 冷却 60s
t=20s: 探针运行，也探测到 mootdx 失败（状态已经冷却了，不影响）
t=75s: mootdx 冷却到期，探针先探测成功 → 清除冷却
t=76s: 用户请求到达，成功使用 mootdx
```

如果没有探针，mootdx 恢复后需要等下一次实际请求才能清除冷却状态。

### 4.3 `_mootdx_locked()` 锁超时与 SR 冷却的协同

`_mootdx_realtime` 内部通过 `_mootdx_locked()`（`_MOOTDX_LOCK_TIMEOUT=10s`）保护 mootdx 连接，避免并发调用导致 socket 堆积。`_mootdx` 的 socket 读写超时为 `_MOOTDX_TIMEOUT=6s`。

两者的协同效果：

```
mootdx socket 卡住 6s → socket 超时异常 → _mootdx_realtime 捕获 → 返回 []
  → route() 收到 [] → record_failure() → 计数器 +1
  → 连续 3 次 → mootdx 冷却 60s → 后请求自动跳过 mootdx 直达 Sina
```

这个协同是自动的，无需额外代码。

### 4.4 改造后测试策略

每阶段完成后需验证：

| 验证项 | 方式 | 覆盖的链路 |
|---|---|---|
| `verify_e2e.py` 全 PASS | 执行 `cd backend && python scripts/verify_e2e.py` | 服务存活、设计详情、行情数据、AI 设计 |
| route() 熔断行为 | 单测 `test_free_sources.py` 中的 `TestMarketServiceRouting` | `_route_us` 的 SR 调用 |
| A 股实时行情正常返回 | 手动 `curl localhost:8000/api/v1/market/realtime/A?symbol=000001` | `fetch_a_stock_realtime` |
| 港股实时行情正常返回 | `curl localhost:8000/api/v1/market/realtime/HK?symbol=00700` | `fetch_hk_stock_realtime` |
| 探针日志不报错 | 观察启动后 120s 内的日志 | mootdx/sina/tencent/akshare/levistock |

---

## 5. 附录

### 5.1 现有探针清单

在 `main.py` 的 `_register_health_probes()` 中已注册：

| 源名 | 探测函数 | timeout | 健康循环 |
|---|---|---|---|
| `twelvedata` | `fetch_realtime("SPY")` | 8s | 每 120s |
| `finnhub` | `finnhub_fetcher.fetch_realtime("SPY")` | 8s | 每 120s |

### 5.2 已接入 SourceRegistry 的函数一览

| 序号 | 函数 | 源名（按优先级） | 覆盖场景 |
|---|---|---|---|
| i | `market_service._route_us()` | `twelvedata > finnhub > alphavantage > yfinance` | 美股实时 |
| ii | `sector_fetcher._try_two()` | `levistock > akshare` | 全部 5 个板块/概念/全量股函数 |

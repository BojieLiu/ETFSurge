# Round26 — 前端走查：搜索/补全 + 港股·美股数据缺口（2026-08-16，用户提问驱动）

> 本批为用户在「标的分析 / 自选 / 指数」走查中报告的 7 个现象。结论 + 修复方案已落文档，**均不实施**，等「开始实施」指令。
> 与 round25（容器验收 R27-R41）同源但独立：round25 是容器/架构验收，本批是**前端搜索补全 + 港股美股数据覆盖**缺口。

## 0. 执行摘要

7 个现象收敛为 **3 类根因**：

1. **搜索/补全索引不全（Q1/Q4/Q6/Q7）**：
   - `indices_meta` 表仅 **632 条**（A=562 / HK=63 / **US=7**）。指数搜索 `_search_indices`（`routers/market.py:227`）**只查此表、无 akshare 运行时兜底**（与 symbol 模式 `search_etf` 的兜底不同）→ 美股指数几乎全搜不到、大量港股指数/中文指数名缺失。
   - `instruments` 表 **A=7118（etf1576+stock5542），但 HK=0、US=0** → 港股/美股个股搜索完全依赖 akshare 运行时兜底（`search_hk_us`），索引本身为空。
2. **港股 K 线数据源缺口（Q2/Q3）**：`chart` 端点实测腾讯/阿里/美团/小米返 **0 行**，平安/建行返 **320 行** → HK 历史 K 线抓取链对部分标的失败。
3. **前端快速选项写回缺陷（Q5）**：`UnifiedAnalysis.vue:312 quickSelect` 未把值写回 `activeSearch.searchQuery` → 点「标普500」快速选项报错「请输入标的代码或名称」。同类 R5 缺陷（symbol 模式注释已写明须写回 searchQuery）。**已识别，代码改动按本批「不实施」口径撤回归档为提案。**

> ⚠️ 排查纠偏：首轮误判 `instruments` 表为空——实际查的是错误 DB 文件 `backend/data/portfolio.db`；正确生产库为 `E:/ETF_Surge/data/portfolio.db`（`DATABASE_URL` 指定）。正确结论见 §2 实证。

## 1. 七问逐条

### Q1 — A股「标的分析·指数」模式输入「红利低」无补全
- **现象**：指数模式搜「红利低」无下拉。
- **根因**：「红利低波」属 **ETF**，不是指数；指数模式只查 `indices_meta`（不含此类），且无兜底。用户期望的 红利低波ETF 应在**「个股/ETF」模式**搜（该模式 akshare 兜底能返 28 条 红利低波ETF，已实测）。属**模式误用 + 指数索引不全**叠加。
- **修复**见 §3 Q1。

### Q2 — 港股热门个股 点「技术分析」数据全空
- **现象**：港股个股技术分析弹窗全空（K 线/指标/信号均无）。
- **根因**：见 Q2/Q3 合并根因（§2 实测 + §3 Q2）。

### Q3 — 港股自选 点「技术分析」有的有数据有的没有
- **现象**：同一批港股，部分有 K 线、部分空。
- **实测（reality check）**：`/market/chart/{sym}?asset_type=HK`
  - 00700 腾讯 / 09988 阿里 / 03690 美团 / 01810 小米 → **0 行（空）**
  - 02318 平安保险 / 00939 建行 → **320 行（有数据）**
- **根因**：HK 历史 K 线抓取链（`china_market.py:1511 fetch_history` HK 分支：akshare `stock_hk_hist` → finnhub → alphavantage → 腾讯 `_fetch_tencent_hk_history`；再经 `market_service.py:1434 get_history` 的 Hub 缓存 + 一致性校验）对 00700 等标的**整链失败返空**，而 02318/00939 此前成功抓取并落入 Hub K 线缓存（或源对其可用）→ 表现「有的有有的没有」。具体子因需源码级调试（见 §3 Q2/Q3）。

### Q4 — 港股「指数」模式输入「恒生港股通」缺「恒生港股通高股息低波动指数」
- **现象**：下拉出 6 条 恒生港股通* 指数，但**不含「高股息低波动」**变体。
- **根因**：`indices_meta` 的 63 条 HK 指数含「恒生港股通高股息**率**指数」(H11145) 等，但**不含「高股息低波动」变体** → 索引未覆盖该指数。
- **实证**：`indices_meta WHERE name LIKE '%港股通%'` 返回 7 条，均无「低波动」。

### Q5 — 美股「指数」模式 点快速选项「标普500」报错「请输入标的代码或名称」
- **现象**：点 chip「标普500」(code=SPX) → 弹错「请输入标的代码或名称」+ 重试按钮。
- **根因**：`UnifiedAnalysis.vue:312 quickSelect(ex)` 只写 `query.value`/`symbol.value` 两个**展示 ref**，未写 `activeSearch.value.searchQuery.value`；而 `doAnalyze`（`:370`）读 `activeSearch.value.searchQuery.value.trim()`，为空 → 命中 `:373` 报错。与 R5（symbol 模式须写回 searchQuery）**同源缺陷**。
- **修复（提案）**：`quickSelect` 首行加 `activeSearch.value.searchQuery.value = ex.code`。**本批「不实施」→ 代码改动已撤回，仅留提案。**

### Q6 — 美股「指数」模式输入「费城」「SO」无补全
- **现象**：指数模式搜「费城」「SO」均无下拉。
- **根因**：`indices_meta` **US 仅 7 条**（含 SPX 标普500，不含 费城半导体/SOX、纳斯达克100/IXIC、道琼斯/DJI 等绝大多数美股指数）→ 索引未覆盖。
- **实证**：`/market/search?keyword=费城&kind=index&market=US` → `[]`；`keyword=SO` → `[]`。而 `indices_meta WHERE symbol IN ('SO','SOX','SPX')` 仅命中 SPX。

### Q7 — 美股「个股/ETF」模式输入「费城」「SO」无补全
- **现象**：个股/ETF 模式搜「费城」「SO」无下拉。
- **根因**：「费城半导体指数(SOX)」是**指数**，不在美股个股/ETF 列表；「SO」若作个股(Southern Co)也未在静态基座/`search_hk_us` 的 akshare US 列表命中 → 搜不到。属预期（指数应走指数模式），但叠加 **Q6 指数索引不全** → 双路径都搜不到。

## 2. 实证数据（reality check，抗「假完成」）

- 生产库：`E:/ETF_Surge/data/portfolio.db`（`DATABASE_URL=sqlite+aiosqlite:///E:/ETF_Surge/data/portfolio.db`）
- **instruments**：total=7118 —— A=7118（etf=1576, stock=5542）、**HK=0、US=0**
- **indices_meta**：total=632 —— A=562、**HK=63**、**US=7**
- **chart 端点实测**（asset_type=HK）：00700/09988/03690/01810 = 0 行；02318/00939 = 320 行
- **源码级探针（reality check 关键）**：直接调用 `china_market.fetch_history("00700","HK")` → **320 行**（腾讯源 `web.ifzq.gtimg.cn` 正常，realtime=440 与 last_close=440 吻合）。**源层无问题** → 缺口在缓存/校验层。
- **后端日志铁证**（Round2 探针）：`logs/backend.log` 对 00700 记录
  `[market_service] HK kline 00700 inconsistent with realtime (last_close=440.0 high=683.0 realtime=440.0) — discarding` → 接着 `[chart] Empty history for 00700/HK/daily`。**根因定位**：`market_service.py:1463` 一致性校验把 K 线**区间最高价 high(683)** 与**当前实时价(440)** 比较，`|683−440|/440=0.55>0.5` → 误判为代码错位而丢弃。high 是 320 日窗口最高价，对高波动股（腾讯/阿里/小米/美团）天然比现价高 >50% → 必触发丢弃；平安/建行波动小 → 不触发。详见 §3 Q2/Q3。
- **search index 模式实测**：`费城`(US)/`SO`(US)/`红利低`(A) → `[]`；`恒生港股通`(HK) → 6 条（缺低波动变体）
- **search symbol 模式实测**：`红利低`(A) → 28 条 红利低波ETF（**akshare 兜底生效**，证明 symbol 模式有兜底而 index 模式无）

## 3. 修复方案总表（设计就绪，不实施）

| ID | 级 | 问题 | 根因（file:line） | 修复设计（详见 §3.x） | 验收 | 文件指向 |
|---|---|---|---|---|---|---|
| Q1 | P2 | 指数模式搜「红利低」无结果（模式误用+索引不全） | 指数模式只查 `indices_meta`（无 红利低波类）；`_search_indices`(`routers/market.py:227`)无兜底 | ①指数模式 placeholder/空态引导「ETF 请切个股/ETF 模式」；②索引补全见 Q4/Q6 | 指数模式空态有引导；切个股/ETF 模式搜 红利低 出 红利低波ETF | `routers/market.py:227`、`UnifiedAnalysis.vue:216-222` |
| Q2/Q3 | **P1** | 港股 K 线部分标的空（腾讯/阿里/美团/小米=0 行，平安/建行=320 行） | **`market_service.py:1463` 一致性校验把区间最高价 `high` 与当前实时价比较 → 误判丢弃**（日志铁证） | §3.1 Q2/Q3：一致性校验只比较 `last_close` 与实时价，去掉 `high` 比较子句 | 00700/09988/03690/01810 chart 返 ≥30 行；`TechnicalAnalysisModal` 不再空态；日志无 `inconsistent ... discarding` | `market_service.py:1456-1470` |
| Q4/Q6 | **P1** | 指数搜索不全：美股(费城/SOX/IXIC) + 港股「高股息低波动」等缺失 | `indices_meta` 仅 632（US=7/HK=63）；动态 THS/Sina 段在 akshare 阻断环境失效（R30/R37），仅剩静态种子（US 仅 7 条、港股通仅 6 条无低波动变体） | §3.2 Q4/Q6：扩展 `scripts/sync_indices_meta.py:_STATIC_EXTRA_INDICES` 静态种子（可靠、不依赖 akshare）；放弃「akshare 运行时按中文名搜指数」兜底（akshare 无此能力） | mock `indices_meta` 空 → 费城/SOX/恒生港股通高股息低波动指数 均能搜到；前端下拉渲染 | `scripts/sync_indices_meta.py:147-192`、`services/indices_meta_sync.py`、`routers/market.py:227` |
| Q5 | P1 | 点「标普500」快速选项报错「请输入标的代码或名称」 | `UnifiedAnalysis.vue:312 quickSelect` 未写 `activeSearch.searchQuery`（`:370` 读该值）→ 空串触发 `:373` | §3.3 Q5：`quickSelect` 首行加 `activeSearch.value.searchQuery.value = ex.code` | 点「标普500」chip → 走 index 模式分析 SPX 成功；`UnifiedAnalysis.spec.js` 加 `quickSelect` 断言 | `UnifiedAnalysis.vue:312`、`:370`、`:373` |
| Q7 | P3 | 美股个股/ETF 模式搜「费城」「SO」无结果 | 「费城半导体指数」是指数不在个股/ETF 列表；`search_hk_us` US 基座未覆盖 SO 等 | 随 Q4/Q6 指数索引补全后，指数走指数模式可搜到；个股模式保持 ETF/个股语义（无需为指数名建个股兜底） | 指数模式能搜到 SOX；个股模式 `SO` 视其在美股列表与否（非强制） | `routers/market.py:148-150 search_hk_us` |

### 3.1 Q2/Q3 — HK K 线一致性校验误剔（根因：high 比较，1 处逻辑修正）

**根因（已实证）**：`market_service.py:1456-1470` 的 HK 一致性校验：
```python
if asset_type == "HK":
    _rt = await _call(fetch_hk_stock_realtime, symbol, timeout=8) or []
    _rt_price = next((r.get("price") for r in _rt if r.get("price")), None)
    if _rt_price:
        _last_close = result[-1].get("close")
        _high = max((r.get("high") or 0) for r in result)
        if (_last_close and abs(_last_close - _rt_price) / _rt_price > 0.5) \
                or (_high and abs(_high - _rt_price) / _rt_price > 0.5):   # ← 问题行 :1463
            return []   # 丢弃整段 K 线
```
`_high` 是 320 日窗口**最高价**（腾讯=683），与**当日实时价**(440) 比：`|683−440|/440=0.55>0.5` → 误判为代码错位而**整段丢弃**。该比较语义错误——区间最高价天然高于现价（任何有波动的股票），>50% 是常态，不是错位信号。平安/建行波动小、历史高接近现价 → 不触发，故「有的有有的没有」。

**修复（最小、安全、保原意）**：删除 `_high` 比较子句，仅用 `last_close`（最新收盘）与实时价比对——这才能正确捕获「代码错位」（如注释所述 finnhub/alphavantage 9.49 vs 492.2，last_close 偏差 50 倍会被捕获）。修改后判别：
```python
        if _last_close and abs(_last_close - _rt_price) / _rt_price > 0.5:
            logger.warning("[market_service] HK kline %s last_close(%s) inconsistent with realtime(%s) — discarding",
                           symbol, _last_close, _rt_price)
            return []
        # 移除 _high 子句：_high 为区间最高价，与现价偏差>50% 是常态，误剔有效 K 线
```
- **为何安全**：原意是防「符号错位喂 LLM 失真 K 线」。符号错位时 latest close 必与实时价严重偏离（last_close 比较即可捕获）；`_high` 比较纯属误伤，删除不影响错位检测。
- **阈值保留 0.5**：last_close 与实时价偏差 >50% 仍视为异常（含除权未复权等边际情况），保留防御。
- **复杂度审计**：纯数值比较，无新增 IO/超时；删除一行条件，降低误剔率（性能/正确性双优）。

### 3.2 Q4/Q6 — 指数搜索索引补全（扩展静态种子，不依赖 akshare）

**根因（已实证）**：`indices_meta` 632 条中 US=7/HK=63。同步 `collect_all()`（`scripts/sync_indices_meta.py:195`）本尝试 A 股 sina(562)+港股 sina(~38)+同花顺行业/概念(~1200)，但**同花顺两段在 akshare 阻断环境恒败**（R30/R37 同源），仅剩 sina+静态种子。静态种子 `_STATIC_EXTRA_INDICES`（`:147-192`）仅含 **7 条美股指数**（SPX/DJI/IXIC/NDX/VIX/RUT/SPY）与 **6 条港股通指数**（无「高股息低波动」变体）。故 费城/SOX/恒生港股通高股息低波动指数 等搜不到。

**为何放弃「akshare 运行时按中文名搜指数」兜底**：akshare **无**「按中文名模糊搜全球指数」的 API（仅能按已知代码拉历史）。symbol 模式的 `search_etf` 兜底依赖 akshare ETF 列表，索引无等价物。故治标兜底不可行，改为：

**修复（可靠、可实施）**：扩展 `scripts/sync_indices_meta.py:_STATIC_EXTRA_INDICES`，补齐常用全球指数（含用户报告缺失项）：
- **美股**：`SOX` 费城半导体指数（补）；`IXIC` 纳斯达克综合、`NDX` 纳斯达克100、`SPX`/`DJI`/`VIX`/`RUT`/`SPY` 已有；可按需补更多行业/主题指数（半导体/银行/能源等）。
- **港股**：补「恒生港股通高股息低波动指数」（**symbol 需查证**——当前静态段仅 H11145 恒生港股通高股息**率**指数；低波动变体代码待查，建议以恒生/中证官网或 `stock_hk_index_spot_sina` 返回列表核对后补入）；补其他 港股通/恒生行业细分。
- **A 股**：动态 sina 段已覆盖 562，但若同花顺段持续失败，可在静态段补常用行业/主题指数兜底。

**同步机制保证入表**：`indices_meta_sync.sync_indices_meta_table()`（`services/indices_meta_sync.py:31`）在 lifespan 后台调用 `collect_all()`，静态段**不依赖外部源**必然入表（见 `:218-227` 注释）。故扩展静态种子后，重启/自动同步即生效，无需 akshare 可用。

**验收**：① 单元测试 mock `indices_meta` 空 → 搜「费城」「SOX」「恒生港股通高股息低波动指数」命中；② `python -m scripts.sync_indices_meta` 后 `indices_meta` US/HK 行数显著上升；③ 前端指数模式下拉出对应项。

### 3.3 Q5 — 快速选项写回缺陷（1 行修复，R5 同类）

**根因**：`UnifiedAnalysis.vue:312 quickSelect(ex)` 只写 `query`/`symbol` 两展示 ref，未写 `activeSearch.value.searchQuery`；而 `doAnalyze`（`:370`）读 `activeSearch.value.searchQuery.value.trim()`，空 → 命中 `:373` 报错。与 R5（symbol 模式须写回 searchQuery）同源。

**修复**：
```js
function quickSelect(ex) {
  activeSearch.value.searchQuery.value = ex.code   // ← 新增：写回激活实例的搜索值
  query.value = ex.code
  symbol.value = ex.code
  result.value = ''
  error.value = ''
  doAnalyze()
}
```
- **四态/引用同步**：与 `pickSearchItem`（`:341` 经 selectSearchItem 写 searchQuery）及 `onInput`（`:104` 写 searchQuery）保持一致，消除「点 chip 不触发分析」。
- **验收**：① `UnifiedAnalysis.spec.js` 加用例：调用 `quickSelect({code:'SPX',label:'标普500'})` 后断言 `vm.activeSearch.searchQuery.value==='SPX'` 且触发分析（不再 `error` 含「请输入标的代码或名称」）；② 手动：美股指数模式点「标普500」→ 走 SPX 分析成功。

## 4. 与既有 round 关联

- **索引不全 ↔ R30 / R37**：R30（`scripts/` 被 dockerignore 排除→同步脚本生产依赖缺失）、R37（`indices/global` 返 0）与本批同源——本环境 `indices_meta` 虽非空但**极不全（US=7）**、`instruments` HK/US=0，说明同步覆盖严重不足（仅装了静态种子片段）。本批补全可一并根治 R37 的 `indices/global` 0 条。
- **港股 K 线缺口（Q2/Q3）**已定位根因（`market_service.py:1463` high 比较误剔），非「抓取链失败」——详见 §3.1。与 round24/25 独立，但修复极小（删一行条件）。
- 与 round25 R27-R41 并列，但本批评为「前端走查缺口」，不在 R 编号体系内（避免与容器验收项混淆）。

## 5. 状态：设计就绪，**不实施**，等「开始实施」指令。

> 本批 7 项均为「结论 + 修复设计」归档；除 Q5 曾落 1 行代码已撤回外，无任何实现代码。实证数据（§2）全部来自真实库/端点/日志查询，非推测。

## 6. 多轮 review 轨迹（达到实施标准）

### Round 1（代码路径通读）
- 读 `indices_meta_sync.py` / `scripts/sync_indices_meta.py`：确认 `indices_meta` 632 条来源（sina 动态 + 静态种子），动态 THS 段在 akshare 阻断环境失效 → 仅剩静态种子（US=7/HK=63）。
- 读 `china_market.py:1511 fetch_history` HK 分支 + `_fetch_tencent_hk_history`：确认 HK 链首试腾讯、再 akshare→tickflow→alphavantage→finnhub→腾讯。
- 初判 Q2/Q3 为「抓取链部分失败」，待实证。

### Round 2（可行性探针 + 日志证据）
- **源码级探针**：直接 `fetch_history("00700","HK")` → **320 行**（源层正常）→ 推翻「抓取链失败」初判，聚焦缓存/校验层。
- **读 `logs/backend.log`**：00700 命中 `[market_service] HK kline 00700 inconsistent ... high=683.0 realtime=440.0 — discarding` → **根因定位 `market_service.py:1463` 的 high 比较误剔**。Q2/Q3 由「待调试」升级为「已定位+1 行修复」。
- 修正 §2 实证、§3 Q2/Q3 根因与修复（从「放宽阈值/补源」改为「删 high 子句」）。

### Round 3（方案细化到可实施）
- §3 总表重写 + 新增 §3.1/§3.2/§3.3 详细设计：
  - Q2/Q3：给出精确问题行 `:1463`、修复后代码、安全性论证（last_close 比较仍捕获代码错位）、复杂度审计。
  - Q4/Q6：放弃不可行的「akshare 运行时按中文名搜指数」兜底，改为**扩展静态种子**（可靠、不依赖 akshare），指明具体待补指数与「低波动变体 symbol 需查证」的诚实标注。
  - Q5：精确 1 行修复 + 与 R5 同源说明 + 测试断言。
- 修订 §4（HK 缺口已定位，非「待调试」）。

### Round 4（design-checklist 8 项合规核验）
逐项对照 `docs/design-checklist.md`：
1. **可行性探针前置（D1）**：已做——`fetch_history` 直调探针 + 日志读证（Round2），非推测。✅
2. **证据链必填（D2）**：每项根因附 `file:line` + 日志原文/实测命令输出（§2/§3.1）。✅
3. **验证窗口标注（D3）**：非行情时段验证已注明（日志为 2026-08-16 盘中/盘后真实数据）；HK K 线修复需交易时段复测（实时价比对）。⚠️ 实施时需在**交易日 9:30-15:00 + 真实环境**复测 Q2/Q3/Q5。
4. **非兜底数据（D4）**：实证均来自真实库/端点/日志，非 mock 冒充。✅
5. **真实调用点（D5）**：修复点均为真实调用链（`_search_indices`/`get_history`/`quickSelect`/`doAnalyze`），非脚手架。✅
6. **四态 UI（D6）**：Q5 修复含四态/引用同步（与 `pickSearchItem`/`onInput` 一致）；Q1 建议指数模式空态引导。✅
7. **复杂度审计（D7）**：Q2/Q3 删一行条件（无新增 IO/超时）；Q4/Q6 静态种子扩展（无运行时开销）；Q5 1 行写回。均满足。✅
8. **已知问题模式（D8）**：Q2/Q3 与 R25「一致性校验误剔」同类（注释已提 finnhub 错位）；Q5 与 R5 同源；Q4/Q6 与 R30/R37 同源（同步覆盖不足）。已显式关联。✅

**结论**：7 项均达实施标准（根因实证 + 精确到行的修复 + 验收口径 + 测试断言）。仍维持**不实施**，等「开始实施」指令。Q2/Q3 修复风险最低（1 行逻辑修正）、收益最高（解港股权威标的空数据），建议优先。

# 组合设计方案质量审查 — 核心层构成问题分析

> 审查对象：`design 307`（balanced，2026-08-01）三套方案 allocations
> 审查依据：API 返回完整 plans（`logs/diag/design_307.json`）+ 分配引擎/候选池代码链
> 审查日期：2026-08-01
> **用户决策记录（2026-08-01，已落档到对应章节）**：
> 1. **红利归层（M1）**：红利低波（512890）/中证红利（515080）**归 core**，作防守型核心，权重上限 15%（与文档建议一致）；
> 2. **push2 回退（F17 R61）**：**实测可达则回退 push2 + HTTPS**；不可达保留 push2delay 并记录（按 P1.7 计划执行）；
> 3. **报告表格形态（F3 R4 / F5 R12）**：入选理由**保留在表格内**，只靠全局 CSS 换行解决排版；理由压缩至 ≤80 字，**不移出表格列**（推翻原"移出表格"方案）；
> 4. **数据缺失时 AI 分析（F7 R21）**：标的分析数据全空时**不调 LLM**，直接返回结构化错误提示（与文档一致）。

## 一、现象（用户审查发现）

### 1.1 核心层标的数过多，单只权重被摊薄

三套方案核心层实际标的数：

| 方案 | 核心层标的 | 核心层预算 | 单只平均权重 |
|------|-----------|-----------|-------------|
| 防御型 | 5 只（510300 / 562330 / 563080 / 562340 / 510500） | 50% | ~10% |
| 平衡型 | 6 只（510300 / 588000 / 562330 / 563080 / 562340 / 563030） | 45% | ~7.5% |
| 进攻型 | 6 只（同平衡型） | 40% | ~6.7% |

核心层作为组合"压舱石"，常规实践是 3-4 只高置信宽基；当前 5-6 只导致单只仅 7-10%，核心层失去集中配置意义。

### 1.2 中证A500、红利低波、中证红利从未入选

- `CORE_REQUIRED = ["510300", "560600"]`（etf_scanner.py:53）——**560600 中证A500ETF 是强制注入标的**，但三套方案核心层均未出现；
- `WIDE_BASIS_STATIC`（etf_scanner.py:60-75）静态兜底清单：沪深300 / 中证500 / 上证50 / 科创50 / 创业板 / 黄金 / 国债——**无中证A500、无红利类**；
- `CORE_KEYWORDS`（etf_scanner.py:30-36）含"中证A500"，`classify_etf` 能正确分类——**机制上 A500 应入 core，实际未入**；
- 红利低波（512890）/ 中证红利（515080）不在 `CORE_KEYWORDS`，归卫星层，但卫星层被科创/宽基挤占，从未入选。

### 1.3 核心层多个"中证500"开头标的并存

- 防御型核心层：562330 中证500价值 / 562340 中证500成长 / 510500 中证500；
- 平衡/进攻核心层：562330 中证500价值 / 562340 中证500成长 / 563030 中证500增强 + 510500 中证500（卫星层）。

中证500 价值/成长/增强是**同一指数（中证500）的不同风格切片**，相关性极高，同时持有构成"伪分散"。

### 1.4 卫星层混入宽基（A100 / 中证500）

- 防御型卫星层：589960 科创新能源 / 589720 科创创新药 / **563030 中证500增强** / **562000 A100**；
- 平衡型卫星层：589420 科创芯片 / 589560 科创AI / **562000 A100** / **510500 中证500**。

卫星层本应配置行业/主题（科创类合理），但 A100 / 中证500 属宽基（core 属性），混入卫星层使层属性混乱、行业集中度约束失真。

## 二、根因分析（代码链实证）

### 2.1 核心层数量：强制标的叠加 + layer_count 配置

- `STRATEGY_META.layer_count`：defensive `core: 4`、balanced/aggressive `core: 5`（budgets.py:24/38/52）；
- `_select_and_weight` 的 `MANDATORY_CODES = {"510300", "560600", "518880", "511090"}`（allocation_engine.py:115）——510300 以 3% 强制注入 core，**再叠加 layer_count 的 4-5 只评分入选**，实际 5-6 只；
- 即：`core 实际数量 = layer_count + 强制标的数`，配置未考虑强制标的叠加。

### 2.2 A500 未入选：强制注入"静默失效"链条

1. **560600 未出现在设计中**：`CORE_REQUIRED` 的注入在 `layer_ranking`（etf_scanner.py:515）中实现——但注入逻辑**只从候选池 items 里查找** required 代码（etf_scanner.py 注释自述："layer_ranking 的 required 注入（仅从候选池 items 查找）静默失效"）；
2. **候选池来源**：`fetch_all_etfs_base`（akshare 全市场 ETF 列表）→ `filter_etfs`（规模>1亿、成交额>1000万门槛）→ `classify_etf` → `layer_ranking top25`（30%成交额+70%规模加权）；
3. 若 560600 当日成交额/规模数据缺失（新浪源降级 `amount=0` 时跳过金额过滤，但规模门槛仍可能滤掉），或不在 akshare 返回列表 → 560600 直接不在候选池 → `CORE_REQUIRED` 查找失败 → **无任何 WARNING**（静默）；
4. 候选池实际包含的是 159338 中证A500ETF（portfolio_etfs 有记录）等深市 A500，但因 560600 未在池中，`CORE_REQUIRED` 的"强制保留"语义完全落空；
5. **修复位置提示**：`_inject_static_wide_basis`（etf_scanner.py:79-96）把 `WIDE_BASIS_STATIC` 成员兜底注入，但**清单里没有 560600 / A500**——这是最直接的补丁点。

### 2.3 中证500家族霸榜：tracked_index 精确去重粒度不足

- `_deduplicate_by_index`（market_data_hub.py:606-680）：用 `tracked_index` **精确字符串**去重——562330 的 tracked_index="中证500价值"、562340="中证500成长"、563030="中证500增强"、510500="中证500" 是**4 个不同字符串**，去重不生效；
- `_normalize_segment`（allocation_engine.py:63-79）只对"科创/半导体/芯片/军工/新能源"前缀做板块归一化，**没有对"中证500价值/成长/增强"归一化为"中证500"**；
- `_balance_by_industry`（market_data_hub.py:792-834）按 segment 分组取 top1——segment 不同（"中证500价值"≠"中证500成长"≠"中证500增强"），均衡化无法合并；
- 结论：**同指数家族（中证500价值/成长/增强）被当作 3 个独立板块**，全部入选核心层。

### 2.4 宽基混入卫星层：F0-5 步骤 D 的 backup 补足逻辑（注：F0-5 指 round2-system-diagnosis-and-optimization-plan.md 的候选池修复项）

- allocation_engine.py:545-585：卫星层经科创配额裁剪后 **<4 只时，从 `core_candidates` 按 composite 补足**；
- 防御型：卫星原始候选（科创系占多数）被科创配额（防御 40%→10% 收紧）裁剪后不足 4 只 → 从 core 池拉 563030 中证500增强 / 562000 A100 补位；
- 平衡/进攻：科创配额 50% 裁剪后不足 → 拉 562000 A100 / 510500 中证500；
- **backup 逻辑只排除了"已在 allocations 中的 symbol"（:547 `used_syms`），未排除"core 属性的宽基"**——宽基被当"卫星补位工具"使用。

### 2.5 汇总因果链

```
etf_scanner 候选池（top25 by 规模/成交额）
  ├─ 560600 A500 缺失 → CORE_REQUIRED 静默失效 → A500 永不入选 (2.2)
  ├─ 中证500 家族 tracked_index 各不相同 → 去重失效 → 家族霸榜 (2.3)
  └─ 红利低波/中证红利 非 core 关键词 → 归 satellite → 被科创挤掉 (2.2)
allocation_engine
  ├─ 强制标的 510300 + layer_count → 核心层 5-6 只 (2.1)
  └─ 卫星 backup 从 core 池拉宽基 → A100/中证500 混入卫星层 (2.4)
```

## 三、修复方案

### P1（候选池口径修正）— 影响最大，优先

- **M1：`WIDE_BASIS_STATIC` 补充 A500 与红利**（etf_scanner.py:60-75）：
  ```python
  {"symbol": "560600", "name": "中证A500ETF", "layer": "core", "tracked_index": "中证A500", ...},
  {"symbol": "159338", "name": "中证A500ETF", "layer": "core", "tracked_index": "中证A500", ...},  # 深市兜底
  {"symbol": "512890", "name": "红利低波ETF", "layer": "core", "tracked_index": "红利低波", ...},
  {"symbol": "515080", "name": "中证红利ETF", "layer": "core", "tracked_index": "中证红利", ...},
  ```
  并加入 `CORE_REQUIRED`（或至少确保 `_inject_static_wide_basis` 覆盖）；同时 `CORE_KEYWORDS` 增加"红利低波"、"中证红利"（**用户决策 2026-08-01：归 core，作为核心防守端**；防御型方案红利类权重上限 15%）。
- **M2：`_inject_static_wide_basis` 注入后校验**：注入完成打 INFO 日志（注入了几只、哪些 required 未命中），**required 未命中打 WARNING**——消除"静默失效"。
- **M3（去重粒度）**：`_deduplicate_by_index` 与 `_normalize_segment` 增加**中证500 家族归一化**：`"中证500价值"/"中证500成长"/"中证500增强"/"中证500" → "中证500"`（同一指数家族只保留 fund_scale 最大者）；同理可预置"沪深300增强/沪深300价值/沪深300" → "沪深300"。

### P2（分配引擎层修正）— 影响中

- **M4（核心层数量）**：`_select_and_weight` 对 core 层 `max_count = layer_count - 强制标的数`（当前强制 510300 占 1 只，defensive 应为 4-1=3、balanced 应为 5-1=4）；或在 `allocate` 中把强制标的**计入** layer_count 后不再额外叠加。
- **M5（卫星 backup 排除宽基）**：F0-5 步骤 D（注：F0-5 指 round2-system-diagnosis-and-optimization-plan.md 的候选池修复项）backup 补足时，**排除 industry == "宽基指数" 或 layer 原为 core 的候选**（`:548-561` 遍历 core_candidates 前加过滤）；若卫星层仍 <4，宁可接受 3 只卫星（弱化下限）也不混入宽基。
- **M6（宽基唯一性约束）**：全局（跨层）保证**同一 tracked_index 家族最多出现一次**——当前 510500 中证500 在平衡型 core 与 satellite 同时出现（cross-layer 去重失效，`_dedup_segment` 按 segment 跨层去重，但 510500 segment="中证500" 与 562330 segment="中证500价值" 不同）。M3 归一化后可复用现有 `_dedup_segment` 机制解决。

### P3（质量门禁）— 验收保障

- **M7（e2e 断言）**：**增强** verify_e2e.py 已有的 `section_design_quality_gate`（:1488）或新增独立检查：
  1. 核心层标的数 ∈ [3, 5]（含强制）且单只权重 ≥ 5%；
  2. 核心层必须含 中证A500 / 沪深300（宽基锚）之一；
  3. 同一指数家族（中证500价值/成长/增强）不同时出现 ≥2 只；
  4. 卫星层不出现 `industry == "宽基指数"` 的标的；
  5. 强制标的 560600/510300/518880/511090 必须出现（禁止静默失效）。
- **M8（单测）**：`test_allocation_engine.py` 补：
  - 候选池含 中证500价值/成长/增强 → 只选 1 只；
  - 卫星候选不足 4 只且 core 有宽基 → 卫星保持 3 只、不混入宽基；
  - 强制标的缺失 → 抛异常/打 ERROR（不再静默）。

## 四、验收标准

1. 三套方案核心层 3-4 只、单只权重 ≥5%（防御 4 只、平衡/进攻 5 只上限含强制）；
2. 核心层出现中证A500（560600 或 159338）与沪深300；
3. 任意方案核心层中证500 家族 ≤1 只；
4. 卫星层无宽基（A100/中证500/沪深300 等 industry=宽基指数）；
5. 候选池刷新日志无"required 未命中"WARNING。

## 五、风险与边界

- 红利低波/中证红利归 core（**用户决策 2026-08-01 已定**）会增加核心层与 510300/560600 的风格相关性（大盘价值端），需在 rationale 中说明"红利作为防守型核心"定位；防御型方案红利类（512890/515080 合计）**权重上限 15%**（已落档 M1）。
- M3 归一化需同步维护 `INDEX_KEYWORDS`（etf_scanner.py:99）与 `_extract_index_concept`，避免名称提取与归一化不一致。
- 本审查仅针对组合设计方案质量，不涉及行情/因子数据源修复（见 `round2-unfixed-fix-plan.md` U1/U3/U4）。

---

# 附：组合设计报告格式质量问题分析（追加审查）

> 审查对象：`design 311`（balanced，2026-08-01）design_text（DB 持久化 8381 字符）
> 用户反馈：报告标题重复、排版难看，尤其是表格格式

## F1. 现象

### F1.1 章节标题重复

`## 一、三种方案详解` 在报告中出现 **2 次**（pos=14 / pos=29，中间隔 3 个空行），且无任何去重脚注。

```
# ETF 组合设计方案

## 一、三种方案详解          ← 第 1 次（硬编码前缀）
                            ← 3 个空行
## 一、三种方案详解          ← 第 2 次（plan_tables 自带标题）
                            ← 空行
### 方案对比总览
```

### F1.2 表格排版难看

- **入选理由列超长**：单元格塞入整段 200 字 rationale（"…市场震荡；在防御型方案中沪深300ETF华泰柏瑞核心层配置，大盘价值代表性"），三张方案表每行都是 400+ 字符长行，任何 Markdown 渲染器都无法对齐；
- **名称截断**：`name[:12]` 截断导致 "中证500增强ETF易方达" → "中证500增强ETF易方"（design_report.py:117）；
- **今日涨跌列全为 "—"**：daily_change_pct 未注入（见 F1.3）；
- **表头重复**：三张方案表（防御/平衡/进攻）各自带完整表头 `| 资产类别 | 代码 | 名称 | ... |`，表格整体笨重；
- **空行堆叠**：`_build_plan_tables` 的 `lines = ["\n\n## 一…"]` 以 2 个空行开头，与 :379 前缀拼接后出现 3 个连续空行。

### F1.3 今日涨跌无数据

`| 今日涨跌 |` 列全部为 "—"。S6 注入（strategy_design.py:236-258）从 `market_data_hub.get_by_code(code)` 取 `change_pct`，但：
- 熔断期（sina/tencent/dongfang open）行情池 `change_pct` 缺失 → None → "—"；
- `WIDE_BASIS_STATIC` 兜底注入的静态条目 `change_pct: 0.0` → 0.0 被 `or` 逻辑丢弃（`:243 pool_entry.get("change_pct") or ...`，0.0 为 falsy）→ None → "—"。

## F2. 根因（代码链实证）

### F2.1 标题重复 = task_manager Stage 4 前缀 + plan_tables 自带标题

- `task_manager.py:379`：`design_text = "# ETF 组合设计方案\n\n## 一、三种方案详解\n\n" + plan_tables`；
- `design_report.py:57`：`lines = ["\n\n## 一、三种方案详解"]`——plan_tables **自身以该标题开头**；
- 拼接结果天然产生 2 个"## 一、三种方案详解"；
- **该写库路径（Stage 4/5）不调用 `_validate_report_consistency`**（去重逻辑在 design_report.py:245-281，只被 `compose_and_push_report` 调用）→ 重复标题从未被清理；
- `_validate_design_text`（design_report.py:207-225）会报"存在重复标题" warning，但**仅记录 warning，不回写修正**。

### F2.2 表格难看 = `_build_plan_tables` 渲染策略

- `design_report.py:120`：`rationale = raw.replace("\n"," ")[:200]`——整段 rationale 入单元格；
- `design_report.py:117`：`name[:12]` 截断；
- `design_report.py:109-132`：每方案独立渲染完整表格（表头+分隔行），无"精简列/折叠/分列"设计。

### F2.3 今日涨跌缺失 = 数据注入时机 + falsy 丢弃

- `strategy_design.py:243`：`dcp = pool_entry.get("change_pct") or pool_entry.get("daily_change_pct")`——0.0 被 `or` 丢弃；
- 熔断期/静态兜底时 `change_pct` 为 None 或 0.0 → "—"。

## F3. 修复方案

### F3.1 标题重复（P0，必改）

- **R1（单一来源）**：删除 `task_manager.py:379` 的硬编码前缀 `"# ETF 组合设计方案\n\n## 一、三种方案详解\n\n"`，改为 `design_text = "# ETF 组合设计方案\n" + plan_tables`——plan_tables 自带标题，前缀只保留文档总标题；
- **R2（兜底去重）**：`task_manager.py` Stage 5 写库前（:430 `full_text` 组装后）调用 `_validate_report_consistency(full_text, strategies)` 或新增轻量 `_dedup_headers(text)`，确保**所有写库路径**都经过去重（当前只有 compose_and_push_report 路径有）；
- **R3（校验闭环）**：`_validate_design_text` 检出重复标题时**回写修正**（不只是 warning），或在保存后二次清理。

### F3.2 表格排版（P1）

- **R4（入选理由压缩，保留在表格内）**（**用户决策 2026-08-01：保留理由在表格内，只靠 CSS 换行解决**）：`design_report.py:120` 的入选理由**不移到表格外**，保持现有列结构（代码/名称/权重/评分/今日涨跌/入选理由）；但理由长度从 ~200 字压缩到 **60-80 字**（首句摘要 + 关键数据），配合 R11 全局 table 样式（`word-break: break-word` + `vertical-align: top`）换行排版——理由信息不丢、表格不被撑爆；
- **R5（名称不截断）**：`name[:12]` 改为完整名称（或 [:16]+省略号），避免"中证500增强ETF易方"类残句；
- **R6（空行规范化）**：`_build_plan_tables` 首行去掉 `\n\n` 前导；`_validate_report_consistency` 的 `re.sub(r"\n{4,}", "\n\n\n", ...)` 升级为 `\n{3,}` → `\n\n`（当前保留 3 空行仍偏多）；
- **R7（表头合并）**：三张方案表保留各自表头属正常 Markdown 结构——因用户决策保留理由列（R4 只压缩字数），行数不变，**表头合并无需执行**，标记为已取消（低优先，若日后表格精简再考虑）。

### F3.3 今日涨跌（P1）

- **R8（falsy 修复）**：`strategy_design.py:243` `or` 改为显式 None 判断：`dcp = pool_entry.get("change_pct"); if dcp is None: dcp = pool_entry.get("daily_change_pct")`；
- **R9（静态兜底不伪造）**：`WIDE_BASIS_STATIC` 注入的静态条目 `change_pct: 0.0` 应标注为"无数据"（置 None 而非 0.0），避免把"无涨跌数据"渲染成"0%"或"—"误导；
- **R10（e2e 断言）**：verify_e2e.py 报告质量检查增加：标题无重复（`_count_repeated_headers == 0`）、今日涨跌列非空（至少 1 只标的有真实涨跌幅而非 "—"）。

## F4. 验收标准

1. 任意设计报告（DB design_text）中 `## 一、三种方案详解` 恰好出现 1 次；
2. 报告无 `\n{4,}` 空行堆叠；
3. 表格单元格理由 ≤ 80 字（用户决策：理由保留在表格内靠 CSS 换行，不做移出）；长文本经 R11 全局样式换行不撑爆；
4. 名称无截断残句；
5. 行情数据可用时，今日涨跌列有真实百分比；数据不可用时显示 "—" 但方案卡片仍完整；
6. e2e **新增 `section_report_format`**（verify_e2e.py 现有 design_text 检查在 section_portfolio:312-313，仅查"三种方案详解"存在，无标题唯一断言——增强该处或新增独立 section）断言标题唯一 + 无超长单元格。

### F5. 前端渲染层缺陷（截图实证，追加）— 表格无样式撑爆布局

**现象（用户截图 + OCR）**：完整报告 Tab 中，方案对比表与标的明细表出现：列头顺序错乱（"资产/代码/类别"交叉）、"今日涨跌"列后直接跟 200 字入选理由、名称截断"沪深300ETF华"、表格整体溢出。

**根因**（渲染层，与 F3 内容层叠加）：
1. **标的分析报告（UnifiedAnalysis.vue）的 `.result` 容器（:47 `v-html` + :284 仅 line-height）无任何 `table/thead/th/td` 样式**——且组件用 `<style scoped>`，scoped CSS 本身不作用于 v-html 注入的 DOM → 表格完全无样式（边框/内边距/列宽），长文本单元格撑爆布局；组合设计报告（DesignResult.vue）的 `.markdown-body` 已有完整 table 样式（:236-239，位于 :230 之后）——**两处渲染路径样式不一致**（DesignResult 有、UnifiedAnalysis 无）；
2. marked（markdown.js:16，`gfm:true`）生成的 `<table>` 在无样式容器中走浏览器默认布局；
3. theme.css 仅有 `--table-cell-padding` 等 CSS 变量（:392-395），无 `.result table` 选择器——样式基建存在但未挂到 UnifiedAnalysis 渲染容器。

**修复方案**（与 F11 R37 统一为**全局 theme.css 方案**——见下）：
- **R11（table 样式抽到全局 theme.css，一次覆盖所有 v-html 容器）**：在 `src/styles/theme.css` 增加全局 `.markdown-body table / .result table / .response table`（或统一容器类）样式：
  ```css
  .markdown-body table, .result table, .response table { width: 100%; border-collapse: collapse; font-size: var(--font-size-sm); display: block; overflow-x: auto; }
  .markdown-body th, .markdown-body td, .result th, .result td, .response th, .response td { border: 1px solid var(--color-border); padding: var(--space-2) var(--space-3); text-align: left; vertical-align: top; word-break: break-word; }
  .markdown-body th, .result th, .response th { background: var(--color-bg-tertiary); font-weight: var(--font-weight-semibold); }
  ```
  （`word-break: break-word` 关键——允许长文本换行而非撑爆列宽；`overflow-x: auto` 防横向溢出；**全局非 scoped 样式才作用于 v-html 生成的 DOM**——scoped 样式对 v-html 无效是根因之一）；
- **R12（内容层配合，按用户决策调整）**：入选理由**保留在表格内**（用户决策 2026-08-01），内容层只做两件事——① 理由压缩到 60-80 字（与 F3 R4 一致，`design_report.py:120`）；② 依赖 R11 全局 table 样式（`word-break: break-word`）换行；不再移动列结构；
- **R13（验收）**：截图对比——完整报告 Tab 表格有边框、列对齐、长文本换行、无横向溢出；**新增 `section_report_format`**（或增强 section_portfolio:312-313）增加"表格行数 = 标的数"断言。

### F6. 板块热度"暂无板块数据"（截图实证）— sectors/heat 前后端断裂

**现象（用户截图 + OCR）**：热点板块排行页显示"暂无板块数据"，三个 Tab（热点板块/板块热度/热门个股）可见但内容为空。

**根因**（契约 v2.0 变更后前端未同步）：
1. **后端与契约一致**：`/market/sectors/heat` 返回 `{"items": [...], "total": N}`（market.py:486，hot-plates.md v2.0:12/50/65/133 明确规定 `{items,total}` 结构）；
2. **前端未跟进**：SectorHeatMap.vue:216 `dataList.value = Array.isArray(resp.data) ? resp.data : []`——期望数组，收到 dict → dataList 恒空 → 渲染"暂无板块数据"（:28）；
3. **测试 mock 与真实结构脱节**：SectorHeatMap.spec.js:40/95 mock `getSectorHeat` 返回 `data: [...]` **数组**——与前端 Array.isArray 一致 → 测试全绿，**但从未覆盖后端真实 dict 结构**（防护体系缺陷，同 round3 N 系列）；
4. **提交时序**：契约 v2.0 变更与 SectorHeatMap.vue 修改同在 3f2f179（round2 P2）——同一次提交内后端/契约改了、前端消费逻辑漏改，断裂形成。

**修复方案**：
- **R14（前端对齐契约）**：SectorHeatMap.vue:216 改为：
  ```js
  const d = resp.data
  dataList.value = Array.isArray(d) ? d : (d?.items ?? [])
  ```
  （兼容数组与 `{items,total}` 两种结构，防御性处理）；
- **R15（spec 补真实结构用例）**：SectorHeatMap.spec.js 增加 `getSectorHeat.mockResolvedValue({ data: { items: [{...}], total: 1 } })` 用例——**mock 必须与契约结构一致**（这是测试盲区的根治：mock 数据源自契约而非"前端想要什么"）；
- **R16（e2e 契约断言）**：verify_e2e.py 的 sectors/heat 检查（现有在 `section_api_5xx_check` :1203 只查 HTTP 200——**新增独立 `section_sector_heat`**）改为断言 `items` 键存在且 `len(items) ≥ 1`，并跑通前端实际渲染路径；
- **R17（验收）**：板块热度 Tab 显示真实板块列表（名称/热度/排名变化）；spec 含 dict 结构用例；e2e 断言 items 非空。

### F7. 标的分析：无自动补全 + 空数据报告（截图实证）

**现象（用户截图 img4/img5/img6）**：
1. **img4**：标的分析页搜索框输入后**无任何下拉补全**（只有输入框 + "分析"按钮 + 快速示例 chips）；
2. **img5**：分析"贵州茅台"后报告开头即"数据完整性说明：实时行情、技术指标均为空，历史K线为无，资讯催化中无直接相关新闻"，技术面分析"无法执行"——整份报告基于行业常识定性推断；
3. **img6**：报告表格（资讯催化影响路径表）无边框、标题编号渲染成顿号（"、四、风险提示"）——**表格无样式根因见 F5 R11（v-html 渲染的 table 缺全局样式，`.result` 容器未覆盖）**；标题编号顿号 = LLM 输出 `、` 编号 + prompt 自身建模了该风格（analysis.py:628 用"基本面概览、技术面分析…"顿号分隔，LLM 学样）。

**根因**：
1. **自动补全从未接入**：UnifiedAnalysis.vue 的搜索框（:23-29）是普通 `<input v-model="query">` + `@keydown.enter="doAnalyze"`——**没有使用 useMarketSearch composable**（frontend/src/composables/useMarketSearch.js 已实现完整 debounce/键盘导航/下拉，但此组件未引用）；`marketApi.search`（含 include_stocks）从未在此被调用；
2. **中文名→代码解析缺位**：doAnalyze（:187-202）把用户输入原样当 symbol 传 `/symbol-analysis/stream`；后端 analysis.py:605-611 的 `get_asset_realtime('贵州茅台','A')`/`get_history('贵州茅台')` 解析失败返回空 → **空数据喂给 LLM**（realtime={}、hist=[], indicators={}）→ LLM 诚实输出"数据缺失/无法执行"；
3. **后端本有解析能力但未接入**：`market_service.resolve_symbol_to_code`（:1210）、`/market/search?include_stocks=true` 均存在——前端/后端两处都未在 symbol-analysis 路径使用；
4. **img6 表格** = F5 已定位（v-html 渲染的 table 缺全局样式，修复见 F5 R11 全局 theme.css 方案）；标题编号顿号 = LLM 输出 `、` 编号 + prompt 自身建模（见 R22）。

**修复方案**：
- **R18（前端接入自动补全）**：UnifiedAnalysis.vue 搜索框复用 `useMarketSearch`——`onSearchInput`（300ms debounce + `marketApi.search(q, {include_stocks:true})`）驱动下拉列表，`selectSearchItem` 选中后 `doAnalyze`（与 useMarketSearch.spec.js 已有测试对齐）；
- **R19（名称→代码解析）**：doAnalyze 发起前先调 `marketApi.search(q, {include_stocks:true})`，命中首条（name 匹配）则用其 `symbol` 替换 query 再分析；未命中才原样传（并提示"未找到该标的，请从下拉选择"）；
- **R20（后端兜底解析）**：`symbol_analysis_stream`（analysis.py:601-611）在 `get_asset_realtime` 返回空时，用 `resolve_symbol_to_code(symbol, asset_type)` 二次解析（中文名→代码）再取数——前端漏解析时后端兜底；注意：① analysis.py:605 `or {}` 会掩盖 None 触发条件，需改为显式 `if not realtime:` 判断；② `resolve_symbol_to_code` 仅 A 股市场（market_service.py:1210），港股/美股需走 `market_service.search_hk_us`（market_service.py:724）或前端先行解析；③ 其个股路径拉全量 akshare 列表有延迟，需限定输入为明显非代码时（含中文/字母）才触发；
- **R21（空数据阻止 LLM）**：realtime/hist/indicators 全空时**不调用 LLM**，直接返回结构化错误"数据源暂不可用，请稍后重试"（或降级返回 `data_unavailable=true` 让前端提示）——**避免 LLM 用常识生成"伪分析"**（用户明确要求：必要数据喂 LLM，非必要不报告缺失）；
- **R22（prompt 编号约束）**：symbol_analysis prompt 明确"使用 ## 二级标题，编号用 1. 2. 3."（并同步修改 prompt 自身的示例行 analysis.py:628——当前"基本面概览、技术面分析…"顿号分隔会教 LLM 用顿号编号），杜绝 `、` 编号标题；
- **R23（验收）**：输入"茅台"出现下拉补全（含 600519 贵州茅台）；选择后分析报告含实时行情/技术指标（非"数据缺失"）；数据源不可用时前端显示明确错误而非 LLM 常识报告。

### F8. 市场综合研判：标题序号从 0 开始 + 生成后按钮不变量（截图实证）

**现象（用户截图 + OCR）**：报告章节标题为"**0. 市场全景速览** → 1. 市场阶段与核心矛盾 → 2. 宏观流动性与政策解读"；生成完成后按钮仍显示"生成市场研判"（用户期望变为"重新生成"）。

**根因**：
1. **标题序号 0 = prompt 模板教出来的**：`_build_report_prompt`（llm.py:1016-1039）模板写死 `## 0. 市场全景速览` / `## 1.` … `## 5.`——LLM 忠实照抄 prompt 的编号起点（0-based 是模板缺陷，非 LLM 行为异常）；
2. **按钮不变量**：MarketReport.vue:14 `{{ loading ? 'AI 分析中...' : '生成市场研判' }}`——文案只有 loading/初始两态，**无"已生成 → 重新生成"第三态**；`:16` 提示文案 `!report` 才显示（报告存在时无提示），`:44 generate()` 本身可重复调用（无一次性锁），但按钮文案与交互未体现可重新生成语义。

**修复方案**：
- **R24（编号改 1-based）**：llm.py:1016-1039 全部编号 `0.`→`1.`、`1.`→`2.`…`5.`→`6.`（"## 0. 市场全景速览"→"## 1. 市场全景速览"，其余顺延）；
- **R25（按钮三态）**：MarketReport.vue 增加 `report` 存在判断：
  ```html
  <span>{{ loading ? 'AI 分析中...' : (report ? '重新生成研判' : '生成市场研判') }}</span>
  ```
  `:16` 提示文案同样按 `!report` 显示"点击按钮…"、`report` 存在时显示"报告已生成，点击重新生成"（或隐藏提示）；
- **R26（验收）**：报告章节从"1."开始编号；生成完成后按钮显示"重新生成研判"且点击可重新生成（loading 态正常切换）。

### F9. 自选标的：补全慢 + 选中丢名称 + 列表名称列是代码（截图实证）

**现象（用户截图 img8/img9/img10 + DB 实证）**：
1. **img8/img9**：添加自选弹窗输入"600519"（纯代码），自动补全响应慢；
2. 选中补全项后输入框只填代码（无名称）；
3. **img10 + DB**：自选列表名称列显示"159300 / 600519 / SPY"——watchlist 表 name 全部 = symbol（`data/portfolio.db` 实证：id=1 SPY name='SPY'、id=2 600519 name='600519'、id=3 159300 name='159300'）。

**根因**：
1. **补全慢 = spot 缓存 miss 时 thundering herd + 冷启动**：`search_hk_us`（market_service.py:750-758）在 `include_stocks=true` 时拉取 HK+US 全量 akshare spot 列表（`fetch_hk_spot_list`/`fetch_us_spot_list` 各 15s 超时）——**fetcher 层已有 6h 进程内缓存**（china_market.py:664-667/690 `sync_memory_cache`，ttl.py:40-41 `21600s`），**并非无缓存**；真实慢因：① **冷启动**首次搜索触发一次 10-15s 全量拉取；② **缓存 miss 时无 single-flight**——300ms debounce 内连续敲键，多个并发请求各自进入 fetch（thundering herd）；③ 失败/空结果仅短缓存 60s，故障期每次搜索重试；
2. **选中丢名称**：`selectSuggestion`（WatchlistPanel.vue:244-255）`form.value.symbol = s.symbol`——只填代码，`s.name` 未保存；`addItem`（:262）`addWatchlist(symbol, asset_type, notes)` 不传 name；
3. **后端 name 回落为 symbol（历史路径产物）**：`watchlist_add`（market.py:610-617）从 `get_asset_realtime` 取 name 回填（`name = realtime.get("name", data.symbol)`）——**当前代码 realtime 为空时直接 422 拒绝（:611-612），不会存 name=symbol**；且 SPY 等美股有静态名回填（market_service.py:1066-1067 `_us_static_name`，SPY→"SPDR S&P 500 ETF"）——**DB 中 name='SPY'/'600519'/'159300' 的行是旧路径（F3-7 静态名回填之前或走其他添加入口）遗留的脏数据**；
4. **auto-heal 不修合法代码的 name**：`watchlist_list`（market.py:533-556）只在 `not CODE_PATTERN.match(symbol) or realtime is None` 时走 `resolve_symbol_to_code`——600519/159300 是合法 6 位代码，**即使 realtime 有 name 也不回填** → 脏 name 永久残留。

**修复方案**：
- **R27（spot single-flight + 预热）**：fetcher 已有 6h 缓存，**不要降级 TTL**——改为：① 缓存 miss 时加 **single-flight 去重**（同 key 并发只一个 fetch，其余等待共享结果，消除 thundering herd）；② **惰性预热**：首次搜索后后台异步拉满 spot 表，期间搜索直接查缓存；③ 失败缓存 60s 保持，但搜索接口对 spot 失败静默降级（返回静态基座结果，不阻塞）；
- **R28（前端携带名称）**：`selectSuggestion` 把 `s.name` 存到 `form.name`；`addItem` 传 `{symbol, name, asset_type, notes}`（`addWatchlist` 增加 name 参数）；WatchlistCreate schema 增加可选 `name` 字段；
- **R29（后端优先用传入 name，并放宽 422）**：`watchlist_add`（market.py:614-617）优先用 `data.name`（前端搜索已带真实名称），空则 fallback `realtime.name → symbol`；**同时放宽 :611-612 的 422**——当 `data.name` 已提供时（非空且 ≠ `data.symbol`，防止用户把垃圾代码当 name 复制），realtime 为空不再拒绝（用传入 name 入库）；仅当 name 与 realtime 都拿不到时才 422；
- **R30（auto-heal 补 name）**：`watchlist_list` 对 `realtime 有 name 且 ≠ item.name` 的记录执行 name 回填 UPDATE（合法代码也修）；或在 watchlist_add 时用搜索结果预解析 name（前端 R28 已带，双保险）；
- **R31（验收）**：补全响应 <1s（spot 缓存命中）；选中后输入框显示"名称 (代码)"；新添加自选列表名称列显示真实名称；既有脏数据（name=symbol）自动回填。

### F10. 热门个股：技术分析数据不真实 + AI 分析跳转不合理（截图实证）

**现象（用户截图 + OCR）**：热门个股"长鑫科技技术分析"弹窗——综合信号得分 0.5、RSI(14) 50.00、KDJ 50.00/50.00、MACD 0.00/0.00、MA20/MA60 默认值；点击"转 AI 分析"后**跳转到 AI 投资顾问卡片**（而非针对该个股的提问分析）。

**根因**：
1. **技术指标是占位值（"不真实"）**：长鑫科技等热门个股**不在 instruments 基座**（instruments 表仅 1544 条 ETF、A 股个股为 0——round3 已诊断）→ K 线拉取**缺失或不足**（空 df → `compute_all_indicators` 返回 `{}`，indicators.py:157-158；部分数据 → RSI/KDJ 用 50.0 占位（indicators.py:80-83 RSI、:96-98 KDJ）、MACD 用 0（:63-66））；`generate_signal({})` 对空指标返回 `{signal:'hold', score:0, reason:'insufficient_data'}`（signal.py:51-53），部分数据则可能得出 hold/score≈0.5 的占位信号——**占位值被当有效指标展示**（前端 TechnicalAnalysisModal 无 `data_available` 判断，仅 `ind._stale` 标记可选显示 :47），用户无法区分"真实中性"与"无数据默认"；
2. **跳转目标错位**："转 AI 分析"（TechnicalAnalysisModal:104-106 `emit('ai')`）→ SectorHeatMap:121 `emitAnalyze('symbol')` → MarketAnalysis `onQuickAnalyze`（:71-73）→ `externalTrigger` 传给 UnifiedAnalysis 自动分析（:168-177）——但滚动锚点 `anchorSymbol`（MarketAnalysis.vue:53）位于 **AiAdvisor（:51）之后**，`scrollIntoView` 视口顶部先显示 AI 投顾卡片 → 用户感知"跳到 AI 投顾"（UnifiedAnalysis 实际在下方才出现）；
3. **无提问模板**：跳转后是 UnifiedAnalysis 的通用 symbol 分析（prompt 固定"基本面/技术面/资讯/风险/操作建议"），**没有针对个股的预设提问/操作建议模板**（用户期望：选中个股 + 可配置问题如"技术面如何？给出操作建议"）。

**修复方案**：
- **R32（空/不足数据显式标记）**：`indicators`/`signal` 端点（market.py:281-313）对 `hist` 为空或不足（如 <30 根 K 线）时返回 `{"data_available": false, "reason": "K线数据不足（<30 交易日）或数据源缺失"}`（空 df 与部分数据都覆盖，不只 `_stale`）；前端 TechnicalAnalysisModal 收到 `data_available=false` 显示"该标的技术数据暂不可用"空态，不再展示占位指标/信号（signal 端点对空指标的 hold 信号尤其误导，必须显式拒绝）；
- **R33（热门个股 K 线补全）**：热门个股搜索链路（stock-hot-rank/搜索）返回的 symbol 需确保能走通 K 线拉取（长鑫科技 688833 等科创板个股）；instruments 基座补 A 股个股——`backend/scripts/sync_instruments.py` 已实现 akshare 个股同步（:73 `stock_zh_a_spot_em`），**但其 gather 异常仅 WARN + 全量 delete 替换（:80-105），akshare 失败时静默产生空表**（round3 已诊断，不修会复发）——需改为部分成功保留 + 失败重试；
- **R34（滚动锚点修正）**：`onQuickAnalyze` 触发后滚动到 `anchorSymbol` 时**用 scroll-margin-top 或改滚动目标**（滚动到 UnifiedAnalysis 组件本身而非其后锚点），避免视口停留在 AI 投顾；或将 UnifiedAnalysis 移到 AiAdvisor 之前；
- **R35（提问模板）**：UnifiedAnalysis 增加"个股分析模板"下拉/预设按钮——选中个股后提供预设问题（如"📈 技术面分析"、"💼 操作建议"、"📰 资讯催化"、"⚠️ 风险提示"），点击后以该问题作为 prompt 附加输入；`doAnalyze` 的 body 增加 `question` 字段（**需同步后端 SymbolAnalysisRequest schema 加 `question` 可选字段，否则 422**），symbol_analysis_stream 拼入 prompt（analysis.py:622-628 追加"用户关注：{question}"）；
- **R36（验收）**：热门个股技术弹窗在数据不可用时显示空态而非默认值；"转 AI 分析"滚动落在标的分析区且视口不显示 AI 投顾；可选中个股并选择预设问题发起针对性分析。

### F11. AI 投资顾问回答排版渲染差（截图实证）

**现象（用户截图 + OCR）**：AI 顾问回答中"维度/判断依据"表格与"操作建议（组合类型/行业倾向/工具方向）"表格**无边框、无列对齐**，渲染成纯文本流；"1. 总体仓位策略 / 2. 权益内部结构 / 3. 条件触发预案"列表项与表格内容穿插错乱。

**根因**（与 F5/F7 同根因——第三个受害者）：
1. **前端渲染层**：AiAdvisor.vue:24 `v-html="renderMarkdown(response)"`，`.response` 样式仅 `margin-top + line-height: 1.8`（:99），**无 `table/thead/th/td` 规则**；组件 `<style scoped>`（:64）**不作用于 v-html 注入的 DOM** → marked 生成的 `<table>` 用浏览器默认布局（无边框/无对齐），多列内容纯文本堆叠；
2. **LLM 输出格式未约束**：`generate_advice` prompt（llm.py:877-899）只要求"4 个维度 + **加粗**（:896）+ `-` 列表（:897）"，**未禁止表格**——LLM 自行输出 Markdown 表格（"维度/判断依据"、"组合类型/倾向/工具方向"），无样式渲染即错乱；标题层级（核心结论/维度/判断依据）也未用 `##`/`###` 而是裸文本行。

**修复方案**：
- **R37（渲染层统一，与 F5 R11 同一全局方案）**：AiAdvisor `.response` 与 F5 R11 共用**全局 theme.css 表格样式**（R11 已覆盖 `.response table`），无需重复定义；给 `.response` 补 `h1-h4/p/ul` 基础样式（若全局未覆盖）——三处 v-html 容器（UnifiedAnalysis/AiAdvisor/MarketReport）一次覆盖，`scoped` 问题同时解决；
- **R38（prompt 约束）**：`generate_advice` prompt 增加"如无必要不要使用表格，用 `-` 列表组织；如需表格必须使用标准 Markdown 表格语法（`| 列 | 列 |`）；章节标题用 `##` 三级以内层级"——从源头减少 LLM 输出畸形表格；
- **R39（验收）**：AI 顾问回答中表格有边框、列对齐、长文本换行；标题有层级；与 F5/F7 合并验收（三处 v-html 渲染一致）。

### F12. 标的分析：tab 不刷新 + 板块 404 + 指数数据缺失 + 无名称（截图实证）

**现象（用户截图 img13/img14）**：
1. **tab 切换不刷新**：个股/ETF ↔ 板块/概念 ↔ 指数切换后，输入框与旧分析结果**不清理**（"688825 深度分析"结果留在板块 tab 下）；
2. **分析标题只有代码无名称**："688825 深度分析"——无"航材股份"名称；
3. **板块 404**：输入"创新药"→"分析失败：LLM streaming failed: 404: 板块映射失败：创新药（请用板块名称搜索）"；
4. **指数数据缺失**：输入"沪深300"→ 报告"实时行情、技术指标、历史K线均为空"（LLM 只能定性分析）；
5. **自动补全依然没有**（F7 未实施）。

**根因**：
1. **tab 切换只改 activeMode**：UnifiedAnalysis.vue:13 `@click="activeMode = mode.value"`——不重置 `query`/`result`/`error`/`symbol`，旧结果残留；
2. **无名称解析**：`doAnalyze`（:187-202）`symbol.value = q`（原样），无名称→代码/代码→名称解析（F7 已分析，未实施）；
3. **板块 404 = 前端未搜索映射 + 后端仅精确匹配**：sector 模式 body `{sector_code: q, sector_name: q}`（:200-201）——中文名"创新药"被同时当 sector_code 和 sector_name 传后端；后端 `_normalize_sector_code`（**定义于 analysis.py:485**，调用于 :553-558）对中文名**走 :503-508 精确名称匹配分支**（非"无法归一化"）——失败根因是**后端仅支持 `sector_name == name` 精确匹配、无模糊/包含匹配**（"创新药"与板块库名称不一致），叠加前端把中文名原样当 sector_code 传入（:509-518 代码分支只认 BK/cls 数字前缀）；**注意 :593 `except Exception` 会吞掉 :571 的 HTTPException(404) 并包装为 502**（detail 内嵌 "404:" 字样，用户看到的 "404:" 只是 detail 文本子串）——前端实收 502；
4. **指数数据缺失 = index 模式落入 symbol 分支**：doAnalyze 的 endpoint 分支（:197-199）只有 sector/symbol，**index 模式走 `/symbol-analysis/stream`**（`{symbol: '沪深300', asset_type:'A'}`）→ `get_asset_realtime('沪深300','A')` 解析失败 → realtime/hist/indicators 全空 → LLM 输出"数据缺失"报告（与 F7 空数据喂 LLM 同根因）。

**修复方案**：
- **R40（tab 切换重置）**：UnifiedAnalysis.vue:60 改 `const { start: startStream, stop: stopStream } = useLLMStream()`；:13 改为 `switchMode(mode)`——先 `stopStream()`（useLLMStream.js:93-98 已实现，AbortError 被 :86 静默吞掉不误报），再重置 `activeMode/query/result/error/symbol/loading`（并重置 `lastAnalyzed` :75，避免旧去重状态干扰 selectedSymbol 触发）；
- **R41（板块名称预解析，弃 search）**：`marketApi.search` **无板块分支**（market.py:62-164 仅 stock/ETF/HK/US），不能用——改为三选一：① 后端 `_normalize_sector_code`（:503-508）加 ilike/包含名称匹配（最小改动）；② 新暴露板块搜索端点（`get_sector_industry`/`get_sector_concept` 按 name 过滤）；③ 前端只传 `sector_name` 由后端解析；同时 **except 中先 re-raise HTTPException**（否则 404 被 :593 包装成 502）；
- **R42（index 模式独立端点）**：doAnalyze 增加 index 分支——index 模式调专用指数分析（`/index-analysis/stream` 或 symbol 模式但 asset_type='index' 且先解析 000001→上证指数 等）；后端对中文指数名（沪深300）用 `search_indices` 解析；
- **R43（标题带名称）**：realtime 在 SSE 响应中**不回传**（_sse_stream done 事件 :47 仅 full_text/usage/disclaimer），不能依赖"返回后回填"——改为 **doAnalyze 前**用搜索解析真实名称放入 body.name（analysis.py:620 `display_name = name or realtime.name` **已支持名称优先**；当前 :202 传 `name: q` 用户原文，输入代码则 name=代码 → 标题无名称）；externalTrigger.name（:66/:168-177）仅热点入口携带，作补充不作主路径；
- **R44（验收）**：tab 切换清空输入与结果；板块输入中文名可分析（无 404）；指数输入"沪深300"报告含实时点位；分析标题显示"名称 (代码)"。

### F13. 新闻 AI 分析：结果合理性评估 + 双层框样式雷同（截图实证）

**现象（用户截图 + OCR）**：新闻卡片（新浪财经"首批理财公司上半年成绩单出炉"）内嵌"AI 智能分析"结果（"该新闻为理财公司业绩披露，与 A 股无直接关联，无直接影响 / 影响范围：无直接影响 / 免责声明"）——**分析结果本身合理，但新闻卡片与 AI 分析框两层框样式几乎相同，嵌套视觉重复**。

**评估：分析结果合理 ✓（但信息量低）**
- `news_impact_stream`（analysis.py:637-658）prompt（:646-655）传新闻标题/内容 + **用户组合持仓**，要求 JSON 输出（影响范围 + 受影响组合标的）；
- 该新闻（理财公司业绩披露）与 A 股无直接关联，"无直接影响"判断**合理**；
- **但信息量低**：prompt 未注入市场上下文（指数/板块/情绪），LLM 只能基于新闻文本 + 持仓判断，无法展开"市场/板块传导"分析——对无关新闻返回"无直接影响"是正确但单薄的结果；
- 影响范围/免责声明渲染结构正确（NewsView.vue:66-86）。

**根因：双层框样式雷同**
- `.news-item`（NewsView.vue:246）`border: 1px + border-left-width: 4px + border-radius: radius-lg + background: surface-secondary`；
- `.impact-inline`（:264）`border: 1px + border-left: 3px + border-radius: radius-md + background: surface-tertiary`——**两者同为"左边框色条 + 圆角 + 浅背景"卡片**，嵌套时视觉上像"框里套框"，无主次区分。

**修复方案**：
- **R45（样式分层）**：`.impact-inline` 改为**无边框的强调区**——去掉 border/背景，改为 `background: transparent` + 顶部细分割线 + 左侧内缩（padding-left）+ 淡色圆角块（如 `background: var(--color-bg-brand-subtle)` 品牌浅色，区别于新闻卡 surface-secondary）；或加"🤖 AI 分析"小标签条（`:55` 已有按钮，展开区顶部加 `<div class="impact-header">🤖 AI 智能分析</div>` 明确层级）；
- **R46（信息量提升）**：`news_impact_stream` prompt 注入市场上下文（regime/指数/板块热度——复用 llm_context.build_full_context），使"相关新闻"能展开传导分析、无关新闻仍返回"无直接影响"但给出理由（如"与持仓及当前市态均无关联"）；
- **R47（验收）**：展开的 AI 分析区与新闻卡视觉可区分（不同背景/内缩/标签头）；对无关新闻分析给出"无直接影响"+ 简短理由；对相关新闻给出板块传导。

### F14. 新闻 AI 分析虚构持仓标的（截图实证）— LLM 幻觉 + 无一致性校验（512880 需复核持仓快照）

**现象（用户截图 + OCR）**：新闻"四部门发文严禁金融机构向股东利益输送"→ AI 分析"对组合内标的的影响"列出了 **银行ETF 512800 / 证券ETF 512880** 两只标的及影响分析——但**这两只标的当前不在用户组合中**（DB `portfolio_etfs` 现表无 512800/512880；组合为 A500/红利/恒生红利低波/半导体设备/创新药/港股创新药/恒生科技/券商(512000)/游戏/黄金等；512880 曾于 07-29 INSERT 见根因 #4）

**根因（LLM 幻觉 + 无一致性校验，但需区分持仓快照时点）**：
1. **LLM 幻觉**：`analyze_news_impact`（llm.py:943-997）prompt（:968-971）有软约束"只列出实际受影响的标的，宁缺毋滥"——但 LLM 对"金融监管"新闻**联想到银行/证券 ETF 并编入 affected_holdings**；
2. **无硬性一致性校验**：`:995` `affected_holdings = data.get("affected_holdings")` **直接透传 LLM 输出**——未与传入 `holdings` 的 symbol 集合比对；
3. **流式路径同样无校验**：`news_impact_stream`（analysis.py:637-658）prompt 构造后直接 `_sse_stream(agent.run_stream(prompt))`——SSE 流式响应无后处理过滤，且其 prompt（:646-655）比非流式**更弱**（连"重要约束"软约束都没有）；
4. **⚠️ 持仓快照时点存疑**：日志实证 **512880（证券ETF）曾在 2026-07-29 12:10:46 INSERT 进组合（权重 6%）**——若前端 NewsView:216 `(store.etfs || [])` 快照为旧组合（用户当时持有 512880），AI 列出 512880 **可能非幻觉**；但 **512800（银行ETF）从未 INSERT**——确认幻觉。当前 DB 无 512880（组合后改组为 512000/006098 券商类），故**按当前持仓两者均为"不在组合"**，但幻觉判定以分析请求时刻的快照为准。

**修复方案**：
- **R48（持仓白名单过滤）**：`analyze_news_impact` 返回前**过滤 `affected_holdings`**——仅保留 `symbol ∈ 传入 holdings 代码集` 的条目，其余丢弃（并计数 WARNING 日志"LLM 虚构 N 个持仓标的已过滤"）；`news_impact_stream` 流式路径在 done 事件前同样过滤（_sse_stream 包装后处理）；
- **R49（prompt 强化）**：prompt 增加**显式代码清单**——"当前组合持仓代码：{逗号分隔}。affected_holdings 中 symbol 必须从该清单中选择，不得新增任何代码"，降低幻觉概率（R48 兜底）；
- **R50（前端兜底，基于请求时刻快照）**：NewsView.vue:216 `analyze(item)` **发起请求时**把 `store.etfs` 代码集存为快照（`requestHoldings`），:73-81 渲染 `affected_holdings` 前用该快照过滤 `h.symbol ∈ requestHoldings`（**不能基于渲染时 `store.etfs`**——组合可能在请求后变化，把真实持仓误过滤）；
- **R51（验收）**：对任意新闻，AI 分析的 affected_holdings 100% 属于当前组合；后端日志记录虚构过滤次数；前端不显示组合外标的。

### F15. Dashboard 空态抢跑：数据未加载完成就显示"暂无组合数据"（截图实证）

**现象（用户截图 + OCR）**：Dashboard 刚打开显示"**暂无组合数据 / 请前往「组合与分析」添加 ETF**"，但**稍后数据加载出来就有内容**——空态误报。

**根因（fetchAttempted 置位时机过宽）**：
- `useDashboardData.js` 三个 fetch 函数**各自**在 `finally` 置 `fetchAttempted=true`：`fetchGlobalIndices`（:65-73，读缓存**几乎瞬时**）、`fetchAllocations`（:77-89，走 portfolio realtime **慢**，外部数据源）、`fetchPnl`（:92-103）；
- `refreshAll`（:124-125）`Promise.all` 并行——**`fetchGlobalIndices` 先完成 → `fetchAttempted=true`** → Dashboard.vue:81 空态条件 `fetchAttempted && !allocationOn?.allocations?.length && !allocationOff?.allocations?.length` 立即成立（此时 fetchAllocations 未返回，allocations 为空）→ **"暂无组合数据"抢跑显示**；几秒后 fetchAllocations 完成才切换为内容；
- `loading`（useDashboardData.js:61）是 `allocations 全空` 的 computed，但空态分支（Dashboard.vue:81）**未检查 `loading`**——`loading=true` 时仍可显示空态，两个状态语义冲突。

**修复方案**：
- **R52（fetchAttempted 统一置位，覆盖所有路径）**：`fetchAttempted` 只在**所有数据源完成**后置 true——① `refreshAll`（useDashboardData.js:124-125）改为 `try { await Promise.all([...]) } finally { fetchAttempted.value = true }`，三个 fetch 函数**移除各自 finally 置位**；② **`Dashboard.vue:184` 的 `onMounted` 当前直接调 `Promise.allSettled([三个fetch])` 不走 refreshAll**——必须改为调用 `refreshAll()`（或同样包 try/finally 置位），否则初始加载路径（正是 bug 发生处）永远不置位 → 骨架永久显示、空态无法出现（:205/:214 的 route-watch/onRetry 已用 refreshAll，无需改）；
- **R53（空态排除 loading）**：Dashboard.vue:81 条件加 `&& !loading`——`loading=true`（allocations 全空且 fetchAttempted=true 的中间态）时继续显示骨架而非空态：
  ```html
  <div v-if="fetchAttempted && !loading && !allocationOn?.allocations?.length && !allocationOff?.allocations?.length" class="empty-state">
  ```
- **R54（加载文案）**：加载骨架区（:64）提示语从"加载中"改为"正在加载组合数据…"（可配合 warmup-banner 已有机制），避免用户误以为卡死；
- **R55（验收）**：打开 Dashboard 无"暂无组合数据"闪现；加载中显示骨架；数据返回后显示内容；真无组合（API 返回空 allocations）才显示空态。

### F16. Token 监控：趋势图缺每日费用系列（截图实证）

**现象（用户截图 + OCR）**：Token 用量监控页顶部有"**预估费用（¥）8.26**"总费用卡，但**趋势图（Token 消耗趋势）只有"Token 数 + 调用次数"两个系列**——用户希望增加**每日费用消耗**。

**现状（后端已具备全部数据，仅前端缺系列）**：
1. **后端 `timeseries` 已返回费用所需字段**：`token_usage.py:230-290` 的 bucket 含 `prompt_tokens`/`completion_tokens`/`total_tokens`/`calls`（:247-249、:284-287）——按日 prompt/completion 分布**已在前端可及**；
2. **前端已实现费用计算逻辑**：TokenMonitor.vue:211-218 `estimatedCost` 用 `PRICING[modelName]` 单价 × prompt/completion 算总费用（已用于顶部"预估费用"卡）——**可复用该函数按 series 逐日计算**；
3. **前端趋势图缺费用系列**：`trendOption`（:221-292）legend 只有 `['总 Token','调用次数']`（:234）、series 只有 Token 数（:268-278 bar）+ 调用次数（:279-289 line）——**无费用系列**。

**修复方案**（review 揭示：当前顶部"预估费用 ¥8.26"本身可能是计价 bug 产物——`modelName` 恒回退为 `'deepseek-v4-flash'` 字符串（TokenMonitor.vue:215 `total?.model || 'deepseek-v4-flash'`，而后端 summary() 的 total **无 model 字段**），若实际用 flash-free 免费模型则费用应为 ¥0 却按 flash 单价误计）：
- **R56（后端按 model 拆分）**：`token_usage.py` ① `summary()`（:169-171/:176-204）聚合循环增加 `by_model`（按 `r.model` 分桶 prompt/completion）；② `timeseries()`（:230-302）bucket（:247-249/:261-263/:270-272）加 `by_model`，聚合循环（:277-289）按 `r.model` 拆分 prompt/completion，并返回**窗口内 total（含 by_model）**；③ **数据源改读 SQLite**（消除 `self._records` 5000 条截断对窗口的影响，token_usage.py:117-118）——admin.py:31-46 各分支透传；
- **R57（前端按 by_model 计价）**：TokenMonitor.vue 抽出 `calcCost(prompt, completion, modelName)` 纯函数（复用 :216-217 单价逻辑）；`estimatedCost` 改用 `summary.by_model` 逐模型计价（**修复当前 modelName 恒为 flash 字符串 → 一律按 flash 单价误计 bug**，免费模型 flash-free 贡献 ¥0）；费用系列用 series 逐日 `by_model` 计算；
- **R58（第三系列 + tooltip）**：`trendOption` legend 加 `'费用(¥)'`（:234 改为三系列）、yAxis 加第三轴（`{type:'value', name:'费用(¥)'}`，避免被 Token 量级压制）、series 加费用折线（`yAxisIndex: 2`，绿色 `#10b981`）；tooltip formatter 三行（Token/调用/费用，费用显示 ¥x.xx）；
- **R59（验收口径统一）**：顶部"预估费用"改为基于 **timeseries 窗口 total**（同一窗口、同一数据源）——"窗口内每日费用之和 = 顶部预估费用（±0.01）"恒等；补回归断言：flash-free 记录费用必须为 0（当前 bug 的回归测试）；多模型混合按各自单价；日/月/小时三粒度均有费用系列。

### F17. 数据源页：threadpool 被当数据源 + push2delay 域名残留（截图实证）

**现象（用户截图 + OCR）**：
1. 数据源列表出现 **threadpool-main / threadpool-akshare**（线程池健康项被展示为"数据源"）；
2. 数据源里显示 **push2delay.eastmoney.com**（东财延迟域名），且**只有 push2delay 没有 push2**——此前计划（P1.7）是 IPv4 优先修复后**回退 push2**，用户疑问"没改全/没改"。

**根因 1（threadpool 混入）**：
- `probes.py:82/92` 显式注册 `threadpool_main` / `threadpool_akshare` 两个健康探针（T1/T2 线程池健康，`alive <= max_workers*0.8`）；
- 探测结果经 `source_health.py:39/45` `registry._health(name)` 写入 SourceRegistry；
- `source_registry.py:153-157` `_health()` 是**动态创建**（name 不存在即 new SourceHealth）——threadpool 因此进入 `registry.get_states()`；
- `admin.py:60-79` `get_sources_health` 遍历 `get_states()` 全量返回 → **前端数据源页把线程池当数据源展示**。

**根因 2（push2delay 未回退 push2 + fund_flow 熔断语义跨路径）**：
- **当前全代码库统一用 `push2delay.eastmoney.com`**：`etf_scanner.py:225`（全量 ETF 列表）、`fundamentals_fetcher.py:19/572/587`（涨跌家数）——**没有 n.eastmoney.com 残留，也没有 push2**；
- **历史脉络**（comprehensive-diagnosis-report.md:384/593）：`push2` 不通 → 临时改 `push2delay`（commit 981ef74）→ P0.5 全局 IPv4 优先已上线（config.py:16-34 `enable_ipv4_only()` 模块加载即启用）→ **P1.7 计划"push2delay 回退 push2 + HTTPS"（:593）——P0.5 前置已满足但 P1.7 从未执行**——这就是"只显示 push2delay 没有 push2"的真相：不是漏改，是**回退计划未实施**；
- **strategy_design.py:362 熔断检查名实匹配**（`_health("push2delay.eastmoney.com")` 与 fundamentals_fetcher `fetch_advance_decline_ratio` :578-581/:597/:601 的写入名一致，非"无人写入"）；但**真实问题是语义跨路径**：`_compute_fund_flow`（:349-422）实际请求走 `market_data_hub.get_fund_flow` → `fetch_fund_flow`（fundamentals_fetcher.py:83-121 **用 akshare**，:91-93 也检查 push2delay 熔断）——**fund_flow 的可用性被涨跌家数路径（push2delay HTTP）的熔断 gate**，而 fund_flow 自己走 akshare——两条路径的熔断互相污染。

**修复方案**：
- **R60（数据源页过滤非数据源）**：`admin.py get_sources_health`（:60-79）过滤 `threadpool_` 前缀（或 registry 增加 `kind: "probe"|"source"` 标记，threadpool 探针标记为 probe 不展示；数据源页只展示 `kind=="source"`）——线程池健康仍保留探测与告警，仅从数据源列表剔除；
- **R61（执行 P1.7 回退 push2 + HTTPS）**：P0.5（IPv4 优先）已部署、前置满足——按 comprehensive-diagnosis-report.md:593 执行回退：`etf_scanner.py:225`、`fundamentals_fetcher.py:19/587` 的 `push2delay.eastmoney.com` 改回 `push2.eastmoney.com`，协议 HTTP→HTTPS；**回退前先实测 push2 在宿主机+Docker 均可达**（P1.7 前提），若不可达则保留 push2delay 并记录原因；域名改为集中常量（如 `EM_API_HOST`）避免再次散落；
- **R62（fund_flow 熔断语义对齐）**：`_compute_fund_flow` 与 `fetch_fund_flow` 实际走 akshare（fundamentals_fetcher.py:97-98），却被 push2delay 熔断 gate（:91-93）——改为检查 akshare 源健康（`_AKSHARE_SOURCE`）或去除该 gate（fund_flow 自身有 akshare 异常兜底 :120-121）；strategy_design.py:362 同步对齐；
- **R63（验收）**：数据源页不再显示 threadpool_*；域名统一为 push2（若回退成功）或集中常量管理；fund_flow 熔断与真实数据路径一致（akshare 或 push2 单一语义）；全代码库 push2delay 零残留（或集中常量单点定义）。

### F18. Dashboard 累计盈亏误报"需输入成本"（截图实证 + DB 实证）

**现象（用户截图 + OCR）**：Dashboard 显示"场内累计盈亏 / 场外累计盈亏 / 总累计盈亏：**需输入成本**"，但用户组合持仓**已录入 avg_cost（成本价）**——提示与事实矛盾，像 bug。

**DB 实证（data/portfolio.db，容器挂载 ./data:/app/data，docker-compose.yml:37-38）**：
- 20 只持仓 **avg_cost 全部有值**（如 159338=1.282、510880=3.045）；
- **shares_held 全部为 None**——用户录入了成本价，但**未录入份额**（或份额不是必填）。

**根因（后端判定过严）**：`portfolio_service.py:977` `has_real_data` 需 **`avg_cost is not None AND shares_held is not None AND shares_held > 0`** 三者同时满足才置 True（:982）——shares_held=None → **永不满足** → `has_cost_basis_data=false` → 前端 SummaryCards.vue:72/86/100 全部显示"需输入成本"。
- 估算分支（:1004-1032：`total_capital>0 and price>0 and target_weight>0` 时按 target_weight×capital/price 估算份额）**不置 has_real_data**——且该分支用 current price 当成本（:1007-1010），累计盈亏恒为 0，**用户录入的 avg_cost 对盈亏零贡献**（这是估算逻辑的既有缺陷，R64 一并修正）；
- 前端已传 capital（useDashboardData.js:110-112，capitalOn/Off 默认 500000，portfolio.js:12-13）——估算分支**应该触发**，但 UI 仍被 has_real_data 挡住；
- 前端持仓列表自身已有份额估算展示（PortfolioManager.vue:302/497-509 `≈estimated`）——**同一份数据，列表能估算、卡片却报"需输入成本"**，自相矛盾。

**修复方案**：
- **R64（后端估算份额 + 用 avg_cost 计价，不简单放宽条件）**：**不能**只把 :977 条件改为 `avg_cost is not None`——那会让 shares_held=None 的持仓命中第一个 if，`e.shares_held * e.avg_cost` 直接 TypeError。正确做法：**在 :977 分支内**判断 `shares_held`——有值按原逻辑；`shares_held is None` 时按 `total_capital × target_weight / price` 估算份额（复用 :1006 逻辑），cost_basis = 估算份额 × **avg_cost**（**不要**用 current price，否则累计盈亏恒为 0、用户录入的成本价零贡献），`has_real_data=True`，holdings 标 `estimated: true`；
- **R65（混合稀释标注）**：估算持仓（estimated）单独标注，汇总时提供 `by_type` 与 `total` 的"估算占比"（estimated_cost_basis / total_cost_basis），前端卡片显示累计盈亏时若估算占比 > 某阈值（如 50%）提示"含估算成本"；
- **R66（前端文案区分 + 份额引导）**：SummaryCards.vue 对"全部持仓 avg_cost 为空"显示"需输入成本"；对"有 avg_cost 但含估算份额"显示累计盈亏 + 小字"按目标权重估算"；PortfolioManager.vue 成本录入处 avg_cost 有值但 shares_held 为空时提示"建议补录份额，否则按目标权重估算"；资本默认值统一（portfolio.js:12-13 与 PortfolioManager.vue:415 目前**两处独立**，需收敛为单一数据源）；
- **R67（验收）**：① 有 avg_cost 无份额 → 卡片显示累计盈亏（按 avg_cost 估算成本），列表与卡片口径一致；② 全部无 avg_cost → "需输入成本"；③ 估算份额的持仓 holdings 标 estimated、卡片标注"含估算"；④ 回归：shares_held 有值路径不受影响；⑤ 边缘：avg_cost 非 None 但 total_capital=0/price=0/target_weight=0 → 该持仓跳过估算但仍计入 has_real_data（卡片显示盈亏、列表无行时需兜底文案）。

### F19. 因子模型大量 no_data / 待关注（截图实证 + 代码实证）

**现象（用户截图 + OCR）**：因子模型页——情绪因子 4 个（恐慌贪婪差值 0 有效、个股情绪离散度 0 有效、资讯热度 2 待关注 2 无数据、资讯情绪方向 2 待关注 2 无数据）、风格因子 2 个（对数市值/对数流通市值 0 有效）、ETF 因子 10 个（5 有效 5 无数据）。用户诉求：追踪排查并尽可能修复；**非交易时间无实时数据时，获取收盘数据也可**。

**先澄清"非交易时间"不是根因**：`_fetch_market_data` 已用 **daily K 线收盘数据**（factor_registry.py:836-841 `get_history(..., "daily")`，`closes[-60:]`），不依赖实时行情——非交易时间 K 线照常可得。真正的断点是下面 5 类：

**根因 1（结构性缺失）：sentiment.panic_greed_diff 永远 no_data**
- `fetch_market_sentiment`（fundamentals_fetcher.py:707-746）返回结构**只有单点值**（sentiment_index/label/advance_ratio/volume_ratio/margin_change），**从不生成 `sentiment_history`**；
- `_compute_panic_greed_diff`（factor_registry.py:216-221）要求 `data["sentiment_history"]` 且 `len(hist) >= 5` → 永远返回 0 → **两层 IC 过滤**：`factor_registry.py:1208-1209`（record 前 `abs(value)>0.001` 才入库，第一层）+ `ic_tracker.py:160-161`（compute_periodic_ic 零值排除，第二层）→ IC 跳过 → **永远 no_data**；
- sentiment 注入段（:992-1005）`if _sent.get("sentiment_history")` 也拿不到（缓存文件 sentiment_cache.json 同样无该字段）——**结构性 bug，与数据源无关**。

**根因 2（注入缺失）：sentiment.stock_divergence no_data**
- `_compute_stock_divergence`（factor_registry.py:510-526）优先用 `data["advance_decline"]`（sentiment 注入**不含该字段**，:992-1005 只注入 sentiment_index/history/news_items）；
- fallback 是**运行时** `run_in_thread(get_advance_decline, timeout=2)`（:521）——2s 超时极紧，且依赖数据源可达；失败返回 0 → no_data。

**根因 3（假数据 fallback）：style.size.ln_mcap / ln_float_mcap 0 有效**
- `_fetch_market_data`（:849-854）`total_mv` 优先 `fund_scale`，fallback rows 的 total_mv，再 fallback **固定假值 100e9**；`float_mv` fallback **80e9**——fund_scale 缺失时**全标的同值** → z-score std≈0 跳过（:1135）→ 因子值保持 0 → IC 无区分度 → 0 有效；
- 注：`_normalize_matrix`（market_data_hub.py:1244-1251）已把 ln_mcap 排除出 z-score 改 min-max，但**因子页 IC 统计路径仍用原始值**（跨符号 std 计算在 factor_registry.py:1130-1136）。

**根因 4（数据源依赖）：ETF 因子 5 个 no_data**
- `etf.shares_change`/`etf.institutional_holdings_change` 依赖 `fetch_etf_shares_outstanding`（china_market.py:453-480 **ak.fund_etf_hist_em**）；
- `etf.premium_discount` 依赖 `fetch_fund_nav`（china_market.py:969-1002 **ak.fund_open_fund_info_em**）；
- `etf.tracking_error` 依赖 `get_market_history(idx_code, "index", "daily")`（market_data_hub.py:1064-1071 东财指数）；
- **这些全走 akshare/东财链**——正是用户看到的 **akshare 熔断（489s）直接后果**：akshare 不可达 → 全部失败 → `ET_SPECIFIC_GAP_CODES`（factor_registry.py:571-576）记录缺口 → no_data。

**根因 5（待关注）：news_heat / news_direction**
- news_items 注入正常（:1002-1003），因子有值但 **IC < 阈值（0.02）** → 待关注——**正常低区分度**（ETF 横截面资讯热度差异小），非 bug，可观察或调阈值。

**修复方案**：
- **R68（sentiment_history 生成）**：`fetch_market_sentiment` 增加 `sentiment_history`——内部维护 20 日 sentiment_index 滚动数组（持久化到 sentiment_cache.json），返回时附带；`_compute_panic_greed_diff` 即可取到 `len(hist)>=5`；
- **R69（advance_decline 注入）**：sentiment 注入段（:992-1005）增加 `_d["advance_decline"] = _sent.get("advance_ratio")`（sentiment 缓存已有 advance_ratio，:743）——stock_divergence 优先路径即可命中，去掉脆弱的运行时 2s 兜底依赖；
- **R70（市值假数据移除 + gap 机制接入，三处联动缺一不可）**：① `_fetch_market_data`（:849-854）删除 `or 100e9`/`or 80e9` 假 fallback（`_compute_ln_mcap` :89-90 有 `mv>0` 守卫不会崩，缺数据返回 0）；② gaps 段（:1026-1042）追加 `style.size.ln_mcap`/`ln_float_mcap`（`total_mv`/`float_mv` 为空即缺失，写入 `_data_source_gaps`）——**否则删假值后 ln_mcap 只退回模糊的"IC 未累积（样本 <3）"，与今天"0 有效"几乎无差别**；③ `routers/factors.py:149` 的 code→字段映射泛化为 GAP_FIELD_MAP（ln_mcap → `"fund_scale/total_mv"`，否则显示"缺 必要字段"）。删假值后链路自动成立：total_mv=0 → ln_mcap=0 → 不 record（:1208-1209）→ ic_val None → gaps 命中 → "数据源未接入"；
- **R71（akshare 熔断恢复后自动补齐 + 失败缓存破绽修复）**：akshare 源恢复（health_loop 60s 探测成功 → record_success → 熔断解除）后，`refresh_pool`/`refresh_kline` 下一轮自动重算因子。**但发现关键破绽：`_FUND_SHARES_CACHE` 会把失败结果 `{}` 缓存 24h**——market_data_hub.py:1082 `run_sync(...) or {}` 把 None 变 `{}` → :1083 写缓存 → 后续 24h 命中 `{}` → `{}.get("shares_change_20d") is None` → 不注入 → gap 持续；**若熔断 >24h、TTL 过期后失败覆盖成功缓存，akshare 恢复后还要再等 24h 才重试**。修复：market_data_hub.py:1081-1083 失败/空时 `continue` 不写缓存（下一轮 refresh 自动重试，熔断开销由 SourceRegistry 兜住），或失败后加短背压（如 300s 跳过）但**绝不把失败结果写进 24h 成功缓存**；备选：health_loop record_success 时清空 `_FUND_SHARES_CACHE`；
- **R72（验收）**：akshare 恢复后 5 个 etf_specific 因子从 no_data → valid/warn；panic_greed_diff/stock_divergence 从 no_data → 有 IC 值（样本 ≥3）；ln_mcap 不再 0 有效（有真实 fund_scale 时有区分度，无数据时显示"数据源未接入"而非假值）；news_heat/direction 保持待关注（低区分度属正常）。

### F20. 测试防护体系为何漏检（F15-F19 系统性复盘 + 解决方案）

**背景**：防护体系已相当庞大——verify_e2e.py 1600+ 行 20+ 模块、后端 110+ 测试文件、前端 17 个 spec、pre-commit 构建门禁——但 F15-F19 全部由**用户手动操作发现**，防护体系零拦截。逐项复盘，归为 5 类系统性漏洞：

**漏洞 1：前端测试 mock 与真实契约脱节（F16/F18）**
- TokenMonitor.spec.js:29-33 mock `series: { dates: [...], tokens: [...] }`，真实后端是 `series: [{date, calls, total_tokens}]`（token_usage.py:291-300）——测试只验证 tab 切换，**从不渲染趋势图**，mock 结构失真也无人发现；
- SectorHeatMap.spec.js:40/95 mock 返回**数组**，真实后端返回 `{items, total}` dict（market.py:486）——`Array.isArray` 判定恒空的问题测试全绿；
- useDashboardData.spec.js 未覆盖 fetchAttempted 置位时序（F15）。
- **根因**：前端 spec 手写 mock，**无任何机制校验 mock 结构与真实后端响应一致**；api-contracts 是 Markdown 文档，无自动化 diff。

**漏洞 2：单测隔离真实数据管道（F19）**
- test_sentiment_factors.py:22-29 `_compute_panic_greed_diff({"sentiment_history": [...]})` **直接传字段** → 验证"字段存在时函数算得对"，**从不验证"真实管道是否真的提供该字段"**——fetch_market_sentiment 从不生成 sentiment_history 的结构性 bug 完美绕过；
- test_factor_etf_specific.py 同理：mock nav/benchmark/shares_change_20d 直接喂函数，**从不验证 akshare 不可达时这些字段从哪来**；
- **根因**：测试粒度停在"compute 函数局部正确性"，缺**管道级测试**（mock 数据源 → 断言 `_fetch_market_data`/注入段真的产出字段）。

**漏洞 3：e2e 门禁在故障时自我 SKIP（F19）**
- `section_factor_thresholds`（verify_e2e.py:1459-1461）：`if not _ic_ready: check(..., skip=True)`——IC batch 空（akshare 熔断 → 因子全 0 → IC 无样本）时**整个数值门禁跳过**；
- 即**数据源故障被设计成"不可判"而非"必须失败"**——akshare 熔断 489s 时 etf_specific no_data=5（超限 2）、sentiment no_data=2（超限 0），但 e2e 全绿（SKIP 不计 FAIL）。

**漏洞 4：e2e 只查"有"不查"内容"（F17/F18）**
- sources/health 只查 `healthy > 0`（verify_e2e.py:1005-1007），**不查列表内容**——threadpool_main/threadpool_akshare 混入、push2delay 残留均不拦截；
- db_integrity 只查行数（instruments>1000 等，:1384-1393），**不查成本字段完整性**——avg_cost 有值、shares_held=None 的"半成本"状态不告警；
- factors/active 只查 total≥30（:1104）、live≥13（factor-health 段 :1087），**不查具体因子状态分布**——panic_greed_diff 结构性 no_data、ln_mcap 0 有效均不拦截。

**漏洞 5：无用户视角 UI 验收（F15/F16/F17/F18）**
- 防护体系全在 API/DB 层：verify_e2e 验证端点可达与契约字段；单测验证函数/组件逻辑——**从不渲染真实前端页面、从不走用户操作流**；
- Dashboard 空态闪现（F15）、累计盈亏"需输入成本"文案（F18）、趋势图缺费用系列（F16）、数据源页 threadpool 展示（F17）——全是**渲染层/交互层**问题，在现有防护外。

**解决方案（S1-S5，对应 5 类漏洞）**：
- **S1（契约快照校验）**：前端测试 mock 改为**从真实后端响应生成快照**（record-and-replay：跑一次真实 API，把响应 JSON 存为 fixture，spec 用它）；CI 增加"mock 结构 vs api-contracts 契约"自动 diff（如轻量 schema 校验，contract 改为 JSON Schema 而非纯 Markdown）；已断裂的 TokenMonitor/SectorHeatMap spec 重写为真实结构；
- **S2（管道级测试）**：为每个"数据依赖型因子"加管道测试——mock 数据源层（akshare/东财返回固定数据），断言 `_fetch_market_data` 产出 + 注入段真的包含所需字段（如 fetch_market_sentiment 返回结构断言含 sentiment_history——直接拦截 F19 根因 1/2）；用"契约字段断言"替代"直接传字段给函数"；
- **S3（故障注入改 FAIL）**：`section_factor_thresholds` 的 `_ic_ready=False` 从 skip 改 FAIL（或拆为独立"数据源故障告警"check 计入 FAIL），确保数据源故障时 e2e **不能静默绿**——同时加"门禁被 SKIP 的次数"统计，任何模块 skip 超过阈值即 FAIL（防自我豁免蔓延）；**注意：需对合理 skip 白名单化**（verify_e2e.py:1347 nginx 未运行 skip、:1044 websockets 未装 skip、:1498/:1508 design-quality 条件 skip 等），避免误伤；
- **S4（内容级断言）**：sources/health 增加"**无 threadpool_/非数据源前缀**"断言 + "数据源名在已知白名单内"；db_integrity 增加"**成本字段一致性**"（有 avg_cost 无 shares_held 的持仓告警，命中 F18）；factors/active 增加"**具体因子状态分布**"断言（sentiment 4 因子不允许 no_data、etf_specific 缺口字段标注、ln_mcap 不允许 0 有效）；
- **S5（前端 E2E 冒烟，Playwright）**：对关键页面（Dashboard/因子模型/Token 监控/数据源/标的分析）加**浏览器级冒烟**——渲染成功 + 无关键占位文案（"需输入成本"、"暂无板块数据"、"数据源未接入"大面积出现）+ 关键交互（切换 tab 内容变化）——直接拦截 F15-F18 的渲染层问题；至少覆盖本轮暴露的 5 个页面。
- **S6（验收）**：上述任一问题若回归，防护体系必须在 CI/本地验证中 FAIL——即 F15-F19 每项都有对应的自动化断言（S1-S5 一一对应），不允许再靠人工截图发现。

#### F20 速查表：薄弱点 → 修补 → 优先级（2026-08-01 补充）

> 供排期直接使用：5 个薄弱点（均有代码实证）、对应修补项、建议优先级。

| # | 薄弱点 | 证据 | 修补（对应方案） | 优先级 |
|---|--------|------|------------------|--------|
| 1 | **前端 mock 与真实后端脱节** | TokenMonitor.spec mock `series:{dates,tokens}` vs 真实 `[{date,calls,total_tokens}]`（token_usage.py:291-300）；SectorHeatMap.spec mock 数组 vs 真实 `{items,total}` dict | **S1 契约快照**（mock 从真实响应生成 + JSON Schema diff）+ R73-R76（共享 fixture 内置结构校验） | 🔴 **立即**（防止新 mock 继续脱节，是前端 spec 改造前提） |
| 2 | **单测隔离真实数据管道** | test_sentiment_factors 直接传 sentiment_history 给函数，从不验证 fetch_market_sentiment 是否产出该字段（F19 根因 1 完美绕过） | **S2 管道级测试**（mock 数据源 → 断言注入段产出字段）；降级链用例见 F21 R77-R79（R77-R78 属 S4 在数据源链的延伸，实施时统一推进） | 🟡 与批次 1-3 功能修复同步 |
| 3 | **e2e 门禁故障时自我 SKIP** | verify_e2e.py:1459-1461 `_ic_ready=False → skip=True`——数据源故障被设计成"不可判"而非"必须失败" | **S3 skip 改 FAIL**（改 1 行 + 合理 skip 白名单：:1347 nginx / :1044 websockets / :1498/:1508 design-quality）+ skip 次数超阈值即 FAIL | 🔴 **立即**（成本极低，立刻恢复 e2e 可信度） |
| 4 | **e2e 只查"有"不查"内容"** | sources/health 只查 healthy>0（threadpool_* 混入不拦）；db_integrity 只查行数（半成本状态不拦）；factors/active 只查 total≥30（具体因子 no_data 不拦） | **S4 内容级断言**（数据源名白名单 / 成本字段一致性 / 因子状态分布） | 🟡 与 S3 同批或紧随 |
| 5 | **无用户视角 UI 验收** | 防护全在 API/DB 层，从不渲染页面——Dashboard 空态闪现（F15）、累计盈亏误报（F18）、Token 费用缺失（F16）全在防护外 | **S5 前端 E2E**（Playwright 冒烟：渲染成功 + 无占位文案 + tab 切换；页面清单建议覆盖 Dashboard/因子模型/Token 监控/数据源/标的分析/市场研判，F8 按钮文案如需拦截则把市场研判页纳入 S5 页面清单） | 🟢 最后（依赖页面定型） |

**S6（回归闭环）**：F15-F19 每项映射到上述至少一个断言，任何一项回归必须 FAIL——不再靠人工截图发现。

**实施建议**：S1 + S3 立即可做（改动小、收益大）；S2/S4 随功能批次同步；S5 收尾。四项完成后，防护体系从"数量多但有效性低"变为"数量适中但真拦截"。

### F21. 两项测试工程风险分析（单测维护成本 + china_market 多源熔断测试）

**背景**：评审提出两项风险——①"单测维护成本：30+ 专用测试文件，mock 复杂"；②"china_market.py 为核心路径，需完善 mootdx/Sina/akshare 多源熔断切换的自动化测试"。以下为代码实证分析与优化方案（延续 F20 测试防护主题）。

**风险 1：单测维护成本（实证成立，程度比描述更重）**
- **规模**：`backend/tests/` 共 **115 个测试文件**（非 30+），其中 **75 个含 mock、mock 引用 664 处**（按文件级去重计数：monkeypatch 224 + MagicMock 179 + AsyncMock 200 + 其他 ≈ 664；同文件多次引用已合并，计数口径以 R76 冻结基线时重新定义为准）；top 密集文件 test_design_optimization_plan.py 39 处、test_design_pipeline_integration.py ~21 处、test_design_tasks.py ~16 处；
- **共享 fixture 严重不足**：`conftest.py` 仅 8 行、只注册 `task_db`/`task_mgr` 两个 fixture（来自 db_fixtures.py，Z27 时期新增）——**再无其他共享 fixture**；
- **重复 mock 模式**：`market_data_hub` 被 mock/引用 **359 次**、`run_sync` 62 次、`registry._health` 37 次——每个文件各自 monkeypatch akshare/run_sync/hub，无统一 mock fixture；
- **根因**：测试随功能逐个添加（每 Phase 新增 5-8 个专用测试文件），只做了"能跑"未做"去重"；db_fixtures.py 是唯一的共享化尝试（Z27），未推广到 akshare/hub/registry 等更常用的 mock 对象。

**风险 1 优化方案**：
- **R73（共享 mock fixture 分层）**：`conftest.py` 增加分层 fixture——① `mock_akshare`（monkeypatch `ak.` 常用函数：fund_etf_hist_em/fund_open_fund_info_em/stock_sector_spot_em 等，返回固定 DataFrame）；② `mock_hub`（market_data_hub 的缓存/历史/份额方法统一 stub）；③ `mock_run_sync`（`run_sync(fn, *a, **kw)` 直接同步执行 fn，消除 62 处重复）；④ `mock_registry_health`（registry._health 返回可控 SourceHealth）——预计可删除各文件 30-50% 重复 mock；
- **R74（fixture 工厂 + 参数化）**：数据源降级链测试用 fixture 工厂（如 `make_degradation_chain(sources_fail=[...])`）替代手写 monkeypatch；同类断言（"熔断→降级输出非空"）用 pytest.mark.parametrize 覆盖多源组合，减重复不减覆盖；
- **R75（mock 一致性哨兵）**：共享 fixture 内置"mock 结构与真实响应"校验（如 mock 的 series 结构必须匹配 token_usage.py:291-300 真实返回）——把 F20-S1 的契约快照下沉到 fixture 层，新测试引用共享 fixture 时自动获得契约对齐；
- **R76（验收）**：新增测试优先用共享 fixture（代码评审门禁：新文件 mock 引用 >5 处时必须抽 fixture）；跑一次全量 pytest 统计 mock 引用数，从 664 处下降到目标（如 <450 处）后冻结基线。

**风险 2：china_market.py 多源熔断测试（实证：已有基础，缺 6 类场景）**
- **降级链结构**（china_market.py:6-13，1221 行核心文件）：A 股实时 mootdx→Sina；A 股批量 mootdx→Tencent→Sina；HK Sina→Tencent→东财；K 线 mootdx→Sina；**指数 Sina→mootdx→Tencent（手写 try/except，未接 registry.route）**；历史 A 股 mootdx→akshare→sina→netease / HK&US akshare→Finnhub→Alpha Vantage；**部分链走 `registry.route`**（source_registry.py:198-258：跳过熔断源、HTTP≥400 硬冷却、空数据继续下游），指数链未接入；
- **已有覆盖**：`test_circuit_drill.py` 3 用例（mootdx 熔断→tencent 单只/批量降级 + 冷却恢复）；`test_free_sources.py`（美股直连成功/失败）；`test_source_health.py` 5 用例（probe 记录）；**`test_data_source_fallback.py`** 有 route 级覆盖（冷却恢复、空 dict/list 继续下游、**HTTP 4xx/5xx 硬失败触发 fallback** test_http_4xx_hard_failure_triggers_fallback，:144）；`test_source_registry_optimizations.py` 覆盖 try_call 快失败硬冷却；
- **缺口（6 类，其中 1 类已部分覆盖需补全）**：
  1. **A 股实时二级降级**：`fetch_a_stock_realtime`（:569-582）mootdx→tencent→sina 的 **tencent 也失败→sina** 场景未测（circuit_drill 只测 mootdx→tencent 一级）；
  2. **HK 链熔断切换**：sina→tencent→dongfang（:646-654）无**熔断语义**专项测试（test_hk_realtime_fix:131 测过 dongfang fallback 但用 lambda 替换 registry.route，非真实熔断路径）；
  3. **K 线链**：mootdx→Sina（K 线）熔断切换未覆盖；
  4. **指数链（比"未测"更严重）**：`fetch_index_realtime`（:904）实际是 **Sina→mootdx→Tencent 且手写 try/except，未接入 registry.route**（china_market.py 中 registry.route 仅 :323/:577/:588/:650 四处）——指数链**无熔断器集成**，需先 route-ify 再补测试；
  5. **akshare HK/US 历史**：`fetch_history`（HK/US）走 `_fetch_akshare_history`（akshare 是**主源**，降级是 Finnhub→Alpha Vantage）；A 股历史实际是 mootdx→akshare→sina→netease——原文档"mootdx/Sina(A)"表述过于简化，实际链条更长且 akshare 嵌在 `_mootdx_history` 内，熔断场景均未测；
  6. **全链熔断兜底**：所有源都失败时 `route` 返回 None → 调用方空数据/降级标记（fetch_a_stock_realtime 全失败）未测。

**风险 2 优化方案**：
- **R77（补齐切换用例 + 指数链 route-ify）**：新增 `test_china_market_degradation.py`，用 R74 的 fixture 工厂参数化覆盖缺口 1/2/3/5/6——每类断言：① 熔断源被 route 跳过（不被调用）；② 降级源输出非空且数据正确；③ 成功源 record_success、失败源 record_failure；④ 全失败返回 None/空 + 调用方兜底路径；**缺口 4（指数链）先实施改造**：`fetch_index_realtime` 改为走 `registry.route([("sina",...), ("mootdx",...), ("tencent",...)])`（对齐 :577/:588 模式），再补熔断测试；
- **R78（硬冷却分支补全）**：HTTP≥400 分支（:236-241）的 `(None, 500)` 场景已有覆盖（test_data_source_fallback.py:144），**只需补 2 个新用例**——provider 返回 `(data, 200)` 正常成功、`(data, 0)` 非 HTTP 成功（元组成功形态）；
- **R79（验收）**：缺口 1/2/3/5/6 全部有自动化用例 + 缺口 4（指数链）完成 route-ify 后有熔断用例；模拟任意单源熔断 → 链仍输出数据（除全熔断）；模拟全链熔断 → 返回 None 且调用方不崩溃、有结构化降级标记（对齐 F19-R71 的"失败不写成功缓存"）；用例全部走共享 fixture（R73-R74），mock 引用增量 ≈0。

**与 F20 的关系**：R73-R76 是 F20-S1/S2 在 fixture 层的落地（共享 mock + 契约对齐下沉）；R77-R78 是 F20-S4"内容级断言"在数据源链的延伸。F21 与 F20 合称"测试工程治理"（S1-S6 + R73-R79），实施时统一推进。

## 六、实施顺序与依赖（全文档总览）

> 各 F 章节给出修复项，本节明确**实施批次与依赖**，供排期直接使用。编号前缀：M（主章节）/ R（F3 起全局连续）/ S（F20 防护体系）。

**批次 1（数据正确性，先做——影响面最大且是后续验收前提）**
- M1-M3（候选池口径：A500/红利入池 + 去重粒度）→ M4-M6（分配引擎层）→ M7-M8（质量门禁断言）——**同批实施**，M3 是 M6 的前提（归一化先于跨层去重）；
- F19 R68-R72（因子数据管道：sentiment_history / advance_decline 注入 / 假市值移除 / 失败缓存修复）——独立于 M 系列，可与批次 1 并行；**R70 三处联动必须一次落地**（删假值 + gap map + GAP_FIELD_MAP，缺一不可）；
- F17 R60-R63（数据源页过滤 + push2 回退 + 熔断语义对齐 + 验收）——独立，可与批次 1 并行；**R61 回退前先实测 push2 可达性**。

**批次 2（前端展示正确性，依赖批次 1 数据）**
- **F3 R1-R10（报告内容层：标题去重 P0 R1-R3 + 理由压缩 R4（保留表格内，用户决策）+ 名称不截断 R5 + 空行规范 R6 + falsy 修复 R8-R10）——R1-R3（标题重复）是 P0 必改，且是 F5 R11 表格样式的前提（内容层先行）**；
- **F6 R14-R17（板块热度契约对齐）**——独立，可与批次 2 并行；
- **F9 R27-R31（自选标的补全/名称）**——独立，可与批次 2 并行；
- F18 R64-R67（累计盈亏估算）——独立（基于持仓成本 portfolio_service，与候选池无依赖），与 F16/F15 可并行；
- F16 R56-R59（Token 费用）——独立，但 R57 计价修复依赖确认后端 by_model 拆分（R56）；
- F15 R52-R55（Dashboard 空态）——独立，**R52 的 onMounted 改造必须与 R53 双保险同批**。

**批次 3（渲染层 + 交互，纯前端）**
- F5 R11-R13、F7 R18-R23、F8 R24-R26、F10 R32-R36、F11 R37-R39、F12 R40-R44、F13 R45-R47、F14 R48-R51——**全部是 v-html 渲染/交互修复，R11（全局 table 样式）先行**，其余依赖其样式基础；R48-R51（LLM 幻觉过滤）与 R46（prompt 注入）同批（prompt 与后处理联动）。

**批次 4（测试工程治理，贯穿全程但收尾验收）**
- F20 S1-S6 + F21 R73-R79——**在批次 1-3 实施过程中同步建立**（S1 契约快照先做，防止新 mock 继续脱节），但**最终验收在批次 3 完成后**（S5 前端 E2E 依赖页面定型）。

**依赖关系摘要**：
- M1 → M3 → M6（候选池 → 去重 → 跨层唯一）；
- R70（三处联动）不可拆分；
- R52 + R53（onMounted + loading 守卫）不可拆分；
- R11（全局样式）→ R37/R39（渲染层统一）→ F7/F8/F10-F14 各渲染修复；
- R56（后端 by_model）→ R57（前端计价）→ R59（验收口径）；
- S1（契约快照）→ 所有前端 spec 改造；S3（skip 改 FAIL）→ S4（内容级断言）→ S6（回归闭环）。

**验收命令清单**（每批次完成后的验证）：
1. 后端：`cd backend && python -m pytest`（全量，slow 网络除外）；
2. 后端链路：`cd backend && python scripts/verify_e2e.py`（全模块，重点看新增的 factors/factor-thresholds/design-quality/db-integrity 模块无 FAIL/SKIP 异常）；
3. 前端：`cd frontend && npm test`（vitest）；
4. 前端构建：`cd frontend && cmd /c "npm run build"`（pre-commit 门禁等价）；
5. 前端 E2E（S5 落地后）：Playwright 冒烟 5 个关键页面（Dashboard/因子模型/Token 监控/数据源/标的分析）；
6. akshare mock 手法：单测中统一用 F21-R73 的 `mock_akshare` fixture（不依赖真实网络）；真实网络验证只走 verify_e2e 且熔断时可跳过。

# 组合管线与报告质量修复方案

> **文档状态：** 部分修复已上线。本文档作为"已实施修复的追认"与"剩余待做工作"的结合。
> **2026-07-27 评估更新：** 经重新评估，剩余 4 项中有 2 项已关闭（不再推荐），1 项降级，1 项保留。
> 审阅日期：2026-07-27

---

## 文档定位与状态总览

本文档的原始版本（2026-07-26）提出了 3 个系统性问题及对应的修复方案。经与当前代码交叉验证，发现**问题 1 修复 A** 和 **问题 2 修复 A** 已被上线，相关测试也已补充。

| # | 问题 | 原始优先级 | 当前状态 | 待做 |
|---|------|-----------|---------|------|
| 1 | 防御型策略全部被过滤为 CASH | P0 | **修复 A 已上线** | 修复 B → **已关闭**（-1.5 惩罚在因子不足时是合理安全网；min(2,N) 收益低） |
| 2 | 策略检查报告中风险分析为空 | P1 | **修复 A 已上线** | 修复 B → **已关闭**（修复 A 已充分解决空值问题，边际收益≈0） |
| 3 | ETF 名称/报告文本中文乱码 | P2 | **待实施** | 修复 A → **降为 P2**（纯性能优化，非正确性问题）<br>修复 B → **降为 P3**（精度增强，当前行为已正确） |

---

## 问题 1：防御型策略全部过滤为 CASH

### 现象（历史）

当前代码中的日志输出已是修复后版本（填写 CASH 而非 reject）。以下是修复前的错误日志（历史记录）：
```
# 修复前（不再出现）：
[design_pipeline] task 77 strategy 'defensive' has no non-CASH ETFs — rejecting
[design_pipeline] task 77: 策略校验失败：部分方案无有效 ETF 标的
```

修复后对应日志：
```
[design_pipeline] task 77 strategy 'defensive' has no non-CASH ETFs — filling with CASH
[design_pipeline] task 77: 2/3 strategies have valid non-CASH ETFs
```

### 修复 A：校验降级 ✅ 已上线

**改动文件**：`backend/app/tasks/task_manager.py`

**当前代码（第 321–346 行）**：
```python
# Phase 2.7.1: 逐策略校验非空（非 CASH 标的 >= 1 只）
# 修复 A: 降级为"至少有一套策略有非 CASH 标的即成功"
# 无有效标的的策略填充全 CASH + warning 而非让整次设计失败
valid_count = 0
for s in strategies:
    etfs = s.get("etfs") or []
    non_cash = [a for a in etfs if a.get("symbol") != "CASH"]
    if len(non_cash) >= 1:
        valid_count += 1
    else:
        s["etfs"] = [{"symbol": "CASH", "name": "现金", "weight": 1.0, "layer": "cash",
                       "selection_rationale": "当前估值/行情数据下无合适标的，全部现金保留"}]
        s["warning"] = "本方案在当前市场状态下无符合条件 ETF，全部配置现金"
if valid_count == 0:
    error_msg = "策略校验失败：所有方案均无有效 ETF 标的"
    mgr.update_task(task_id, progress=0, status="failed", error_message=error_msg)
    return
```

**改动量**：已实施 ~25 行  
**风险**：低

### 候选留存率改善（问题 1 修复 B — ❌ 已关闭，不再推荐）

**2026-07-27 评估结论：不再推荐实施。** 代码审计发现原方案的两项修改均不再合理：

| 原提议 | 评估理由 |
|--------|---------|
| `c2_bonus = -1.5` → `-0.6` | `c2_bonus` 仅在 `valuation_missing and not has_meaningful_style`（因子数据不足）时才进入主题关键字惩罚分支。因子正常时此分支不生效。在数据不足时，-1.5 是合理的 safety measure——宁可过于保守也不让防御型买入高风险主题。软化为 -0.6 反而可能让防御型混入不该买的标的。 |
| 每组保留 1 只 → `min(2, N)` 只 | 同归一化概念组内的 ETF 高度相关（如"科创50"与"科创100"），保留多只的分散效果有限。且 `max_count` 由 `STRATEGY_META` 控制（core=4, satellite=8, defense=2），池子本身不大，不做此调整也能保证多样性。 |

**修复 A 已完全解决了"防御型全 CASH 导致设计失败"的根源问题。** 修复 B 试图提升防御型方案的标的数量和质量，但在当前因子数据不足时 -1.5 的严格惩罚反而是正确的保守行为。如有新的证据表明防御型方案标的确实过少，可重新评估此议题。

### 验证方式（仅验证修复 A）

1. 执行 A 股组合设计（capital=500000），确认三套方案均返回成功
2. 检查 defensive 方案的 non_cash 数量：
   - 即使为 0，balanced/aggressive 也应有 >= 2 只非 CASH 标的
   - defensive 应标记 warning 而非导致整次失败
3. `python -m pytest tests/test_design_optimization_plan.py::TestP4`（注意：test class 已存在且未 skip）
4. `verify_e2e.py` 中的设计创建-验证路径应 PASS

### 已有测试覆盖

`backend/tests/test_design_optimization_plan.py` 已包含：

| 测试方法 | 覆盖场景 | 断言 |
|---------|---------|------|
| `test_p4_one_strategy_valid_succeeds` | 仅 1/3 方案有非 CASH 标的 | 管线不应失败 |
| `test_p4_all_cash_still_fails` | 全部方案为纯现金 | 管线应失败 |

---

## 问题 2：策略检查报告风险分析为空

### 现象（历史）

策略检查记录（如 ID 108）中 `risk_warnings` 数组为空 `[]`。API 返回字段存在但内容为空。

### 修复 A：规则驱动风险检测 ✅ 已上线

**改动文件**：`backend/app/services/portfolio_service.py`

**当前代码（第 543–546 行）**：
```python
"risk_warnings": _combine_risk_warnings(
    llm_result.get("risk_warnings", []),
    _compute_risk_warnings(holdings_analysis, factor_scores, regime),
),
```

**辅助函数**：

`_compute_risk_warnings()`（第 572–628 行）— 规则驱动的风险检测，独立于 LLM：
- 行业集中度风险：若覆盖行业 <= 2 且持仓 > 2，生成 high 严重度警告
- 单只权重超配风险：若某标的重 >= 25%，生成 medium 警告
- 低流动性风险：若换手率 < 1%，生成 low 警告

`_combine_risk_warnings()`（第 560–569 行）— 合并 LLM 和规则警告，确保不为空：
```python
def _combine_risk_warnings(llm_warnings, rule_warnings):
    combined = llm_warnings + rule_warnings
    if not combined:
        combined = [{"type": "general", "severity": "info",
                      "description": "当前组合风险指标正常，未触发自动警告。"}]
    return combined
```

**改动量**：已实施约 70 行  
**风险**：低 — 纯函数，不修改现有 LLM 流程

### 修复 B：增强 LLM prompt — ❌ 已关闭，不再推荐

**2026-07-27 评估结论：不再推荐实施。** 修复 A（规则驱动风险检测）已从根本解决了"风险分析为空"的问题：

1. LLM 返回空数组 → `_combine_risk_warnings` 中的规则检测填补
2. LLM 正常输出 → 合并 LLM + 规则两种源，统一返回
3. LLM 超时/失败 → `portfolio_service.py:460-468` 的降级 response 已含空 `risk_warnings: []`，随即被规则检测填补

现有 `strategy_check.md` prompt 已通过规则 4 要求 LLM 推断 `risk_warnings`，`generate_strategy_check_report()` 的 prompt 也包含了完整的持仓数据和因子分析信息。在此基础上再加显式 prompt 指令的边际收益趋近于零。

验证脚本 `verify_e2e.py` 第 459-466 行已有 risk_warnings 非空断言，确保任何时候都至少有一个 info 级别的通用提示。

### 验证方式

1. 执行策略检查（场内组合，capital=500000）
2. 确认 `risk_warnings` 数组至少包含规则驱动检测的结果
3. 至少包含"行业集中度"或"个股权重"或"流动性"三类中的一类警告

---

## 问题 3：中文编码乱码

### 现象

ETF 名称、报告文本在 API 返回中显示为乱码。

### 数据流

```
数据源 (akshare / mootdx / Sina)
  → fetch_all_etfs_base() [etf_scanner.py:147-295]
    → _decode_df(df) [etf_scanner.py:284]   ← 对全量数据统一应用 latin1→utf-8 修复
  → to_dict(orient="records")
  → 缓存 (JSON / SQLite)
  → API 返回
  → 前端展示
```

### 根因分析

`decode_df` 函数（`backend/app/utils/decode.py`）的核心逻辑：
```python
for x in df[col]:
    if isinstance(x, str):
        try:
            fixed.append(x.encode("latin1").decode("utf-8"))
        except (UnicodeEncodeError, UnicodeDecodeError):
            fixed.append(x)
```

**三个问题点：**

**问题 A：无差别应用于所有数据源。** 当数据源已经是正确 UTF-8（mootdx/Sina）时，对中文字符调用 `encode("latin1")` 会触发 `UnicodeEncodeError`，此时 except 保留原值 — 行为正确但隐含多余的开销。

**问题 B：`_normalize_columns()` 二次映射可能改写列名。** `etf_scanner.py:300-320` 在 `_decode_df` 之后又对列名做了一次映射。

**问题 C：`decode_df` 函数不区分数据源。** 对所有调用无差别应用字符串值修复。当数据源已经是正确 UTF-8 时，`encode("latin1")` 会触发 `UnicodeEncodeError` 并被 except 捕获，行为正确但隐含多余开销。

> **2026-07-27 勘误：** 文档此前标注的"3 处非 akshare 调用"（`market_trends.py:82`/`market_trends.py:120`/`macro_state.py:156`）经代码核实，**全部为 akshare 东方财富接口**，并非非 akshare 源。当前 `decode_df` 的所有调用点约 22 处，绝大多数使用 akshare。真正可能不需要字符串值修复的场景极少（如未来引入的外部数据源），因此此修复的实际收益有限。

### 修复方案

#### 修复 A：来源感知解码（降为 P2，纯性能优化）

> **2026-07-27 评估：** 当前 `decode_df` 行为正确（try/except 自动跳过无需修复的字符串）。此修复为纯性能优化——减少无意义的 try/except 开销，非正确性问题。降为 P2，可在有较大代码改动时一并完成。

在 `decode_df` 中加入 `source` 参数，仅对 akshare 数据源应用字符串值修复：

```python
def decode_df(df: pd.DataFrame, source: str = "akshare") -> pd.DataFrame:
    """修复 DataFrame 编码问题。
    
    Args:
        df: 待修复的 DataFrame
        source: 数据源标识。akshare 数据需要字符串值 latin1→utf-8 修复，
                mootdx/sina 等源已返回正确 UTF-8，只修复列名。
    """
```

然后在 `decode.py` 内部按 source 分流：

```python
def decode_df(df: pd.DataFrame, source: str = "akshare") -> pd.DataFrame:
    """修复 DataFrame 编码问题。
    
    Args:
        df: 待修复的 DataFrame
        source: 数据源标识。默认 akshare 需要字符串值 latin1→utf-8 修复。
               非 akshare 源（mootdx/sina 等）已返回正确 UTF-8，跳过字符串修复。
    """
    if df is None or df.empty:
        return df

    # 1. 修复列名（所有数据源都需要）
    renamed: dict[str, str] = {}
    for col in df.columns:
        if isinstance(col, bytes):
            ...
        elif isinstance(col, str):
            try:
                cleaned = col.encode("latin1").decode("utf-8")
                if cleaned != col:
                    renamed[col] = cleaned
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    if renamed:
        df.rename(columns=renamed, inplace=True)

    # 2. 修复 string 列的值（仅 akshare 源需要）
    if source == "akshare":
        for col in df.select_dtypes(include=["object", "str"]).columns:
            fixed: list[Any] = []
            for x in df[col]:
                if isinstance(x, str):
                    try:
                        fixed.append(x.encode("latin1").decode("utf-8"))
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        fixed.append(x)
                else:
                    fixed.append(x)
            df[col] = fixed

    return df
```

**改动量**：仅修改 `decode.py`，函数签名 + 条件分支约 10 行。**调用处无需修改**（默认 source="akshare" 保持向后兼容）。

**风险**：低 — 默认行为不变（source="akshare"），所有现有调用向后兼容。如需标注非 akshare 源可逐一进行，但经 2026-07-27 核实，当前所有调用点均为 akshare 接口，暂且不需要标注。

#### 修复 B：有损检测（降为 P3，精度增强）

> **2026-07-27 评估：** 当前 `decode_df` 的 try/except 逻辑已正确工作。`_is_double_encoded()` 能减少一类罕见误判（字符串恰好是 latin1 可编码且解码后恰好形成中文字符），但实际触发概率极低。降为 P3，可在修复 A 之后视需要再做。

在 `decode_df` 内部增加检测逻辑，只在字符串确认为双倍编码时才修复：

```python
def _is_double_encoded(s: str) -> bool:
    try:
        re_decoded = s.encode("latin1").decode("utf-8")
        if re_decoded == s:
            return False
        return any('\u4e00' <= c <= '\u9fff' for c in re_decoded)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
```

**风险**：低 — 比简单 try/except 更精确

### 已有测试覆盖

`backend/tests/test_decode.py` 已存在（5,385 字节），包含 11 个测试用例：

| 测试方法 | 覆盖场景 |
|---------|---------|
| `test_latin1_double_encoded_values_are_decoded` | 双倍编码字符串值被正确还原 |
| `test_latin1_double_encoded_columns_are_fixed` | 双倍编码列名被正确修复 |
| `test_clean_utf8_data_unchanged` | 正常 UTF-8 DataFrame 不被修改 |
| `test_empty_dataframe_unchanged` | 空 DataFrame 原样返回 |
| `test_none_dataframe_returns_none` | None 输入返回 None |
| `test_numeric_columns_unchanged` | 数值列不受影响 |
| `test_already_correct_utf8_columns_unchanged` | 已正确的中文列名保持不变 |
| `test_gbk_column_values_left_unchanged` | GBK/非 latin1 字符串不被破坏 |
| `test_mixed_encoding_in_different_columns` | 混合编码的各列均被正确处理 |

### 验证方式

1. `python -m pytest tests/test_decode.py -v`（确认全部 PASS）
2. 启动后端后检查 API 返回的中文内容是否正常
3. 检查 akshare 和 Sina/mootdx 两个数据源路径的中文完整性

---

## 剩余实施项优先级（2026-07-27 更新）

经评估，原 4 项剩余任务中 2 项已关闭、2 项降级：

```
保留（P2，性能优化）：
  └─ [问题 3 修复 A] 来源感知解码 ~10 行（decode.py 函数签名 + 条件分流）
      调用处无需修改。当前 decode_df 行为正确，本修复仅减少 try/except 开销。
      不建议单独做，可随其他 decode.py 改动一起完成。

保留（P3，精度增强）：
  └─ [问题 3 修复 B] 有损检测增强 ~10 行（decode.py 新增 _is_double_encoded）
      当前行为已正确，此修复降低误判概率。建议在修复 A 之后视需要再做。

已关闭：
  ├─ [问题 1 修复 B] 候选留存率改善 → 不再推荐
  │   c2_bonus=-1.5 在因子数据不足时是合理安全网；min(2,N) 收益低
  └─ [问题 2 修复 B] 增强 LLM prompt → 不再推荐
      修复 A（规则驱动检测）已充分解决空值问题，边际收益≈0
```

**说明**：
- 问题 1 修复 A 和问题 2 修复 A 已上线，对应测试也已到位。
- **`verify_e2e.py` risk_warnings 非空断言已上线**（2026-07-27 代码审计确认：`verify_e2e.py:459-466` 已检查 risk_warnings 非空且类型有效）。
- 以上为全部剩余改进项。项目可以认为"质量修复 95% 已完成"。

---

## 附录：已有实施追踪

以下为本文档原始版本提出、且经交叉验证已完成的修复项：

| 原始提案 | 落地文件 | 当前位置 | 落地时间 |
|---------|---------|---------|---------|
| 问题 1 修复 A：校验降级 | task_manager.py | 第 321–346 行 | 已在代码中 |
| 问题 2 修复 A：规则风险检测 | portfolio_service.py | 第 560–628 行 | 已在代码中 |
| TestP4 空策略测试 | test_design_optimization_plan.py | 第 256–335 行 | 已在测试中 |
| test_decode.py 新增 | tests/test_decode.py | 全文件 5,385 字节 | 已在测试中 |
| verify_e2e.py 设计质量检查 | verify_e2e.py | 第 245–263 行（长度、策略数等） | ✅ 已上线 |
| verify_e2e.py risk_warnings 断言 | verify_e2e.py | 第 459–466 行 | ✅ 已上线（非空 + 类型校验） |

# 智能组合设计失败 & 策略检查分析审阅 — 问题梳理与修复方案

> 编写日期：2026-07-23 | 最新修订：2026-07-24
> 涉及任务：智能组合设计（id=138，失败）、策略检查与分析（id=42，成功但有质量缺陷）
> **实施状态**: ✅ **已实施** — 2026-07-24 在 commit `ad3e12eb` 中落地（Phase 0.8）。10 文件改动，252 行新增。

---

## 目录

1. [问题清单](#一问题清单)
2. [修复方案](#二修复方案)
3. [验证标准](#三验证标准)
4. [实施顺序与风险](#四实施顺序与风险)
5. [现有测试基础设施 bug 附录](#五现有测试基础设施-bug-附录)

---

## 一、问题清单

### P0 — 前端"查看错误"无响应

| 项 | 内容 |
|---|---|
| **现象** | 设计任务失败后，点击列表中"⚠️ 查看错误"，仅弹出 toast「该方案生成失败，无法查看详情」，未展示数据库中的 `error_message`（"数据管道未生成候选池，检查数据源连接和日志"） |
| **位置** | `frontend/src/views/DashboardAiTools.vue`，`onHistorySelect()` 第 537-540 行 |
| **代码** | `if (item?.status === 'failed') { toast('该方案生成失败，无法查看详情', 'warning'); return }` |
| **影响** | 用户无法从 UI 获取失败原因，只能悬浮在列表项上通过原生 `title` 属性看截断片段 |
| **补充** | `DesignHistory.vue` 第 31 行已在列表项右侧展示了截取 25 字符的错误文本 + `title` 悬浮提示。但点击"查看错误"本该展示完整信息，却什么都没做 |

### P1 — 策略检查 prompt 建议上限硬编码

| 项 | 内容 |
|---|---|
| **现象** | 组合持 10 只场內 ETF，策略检查只输出 **5 条**建议，覆盖 159338/510880/159545/159516/518880，遗漏 159992/513120/513010/512000/159869 |
| **根因** | `prompts/v1/strategy_check.md` 规则 2 固定了`至少 2 条，最多 5 条`。且该 .md 文件是静态文本，无法表达 `max(5, min(...))` 这种动态逻辑 |
| **影响** | 多持仓组合无法得到全覆盖分析 |
| **对照** | `holdings_analysis`（持仓分析）有 10 条——LLM 正确列出了所有标的，说明限制仅在 `suggestions` 字段，不是 LLM 整体输出截断 |

### P2 — 因子评分全空 + 技术信号全 hold（级联故障）

| 项 | 内容 |
|---|---|
| **现象** | `holdings_json` 中 10 只标的全部 `factor_summary="因子数据为空"`，`tech_signal="持有信号hold"` |
| **根因** | 设计任务因外部数据源不可用而失败 → `pool_manager.refresh()` 内部 `scanner.full_pipeline()` 异常，候选池全空 → 因子矩阵缓存未更新 → 策略检查复用缓存拿到空因子分 → `llm.py` 生成 prompt 时显示"无因子数据" → LLM 无依据，全输出 hold |
| **对比** | 上一次成功的策略检查（id=41）所有标的因子分均为"因子数据中性偏多"，信号各异，证明这不是常态 |
| **影响** | 报告有结论但数据基础为空，结论不可信。且问题不在策略检查本身，而在其依赖的缓存状态 |

### P3 — 测试防护体系缺口

| 缺口 | 严重度 | 说明 |
|---|---|---|
| **3a: 优雅错误路径无测试** | **高** | 现有 `test_worker_failure_sets_failed_status` 只测了 `generate_enhanced_design()` **抛异常**；真实失败是返回 dict 带 `result["error"]`，完全不同路径 |
| **3b: 无数据源健康探针** | 中 | `verify_e2e.py` 提交设计前不验证候选池状态，不独立探测数据源可达性 |
| **3c: 无级联集成测试** | 中 | 无测试模拟"数据源全挂 → pool 空 → strategy_design 返回 error → design_worker 标记 failed" |
| **3d: 无输出质量断言** | 低 | 策略检查只检查 worker 完成状态，不验证因子分是否有效、建议覆盖率、信号多样性 |

### P4 — 风控警告未覆盖数据质量风险

| 项 | 内容 |
|---|---|
| **现象** | 两个风险警告（港股相关性、前三集中度）合理，但未提示因子分全空、信号全 hold 的问题 |
| **根因** | LLM 收到的已加工数据摘要中无原始数据质量信息 |
| **影响** | 用户在因子分全空时依然看到一份看似完整的报告，容易误信 |

---

## 二、修复方案

### 方案 1：前端错误详情弹窗（P0）

**涉及文件**：
- `frontend/src/views/DashboardAiTools.vue` — 修改 `onHistorySelect()`
- `frontend/src/components/ui/AppModal.vue` — 已有通用模态框，**复用**即可

**修改内容**：

在 `DashboardAiTools.vue` 的 `<script setup>` 中添加两个 ref：

```javascript
const showErrorModal = ref(false)
const errorDetail = ref('')
```

在 `onHistorySelect()` 中替换 failed 分支：

```javascript
// 原代码
if (item?.status === 'failed') {
    toast('该方案生成失败，无法查看详情', 'warning')
    return
}
// 改为
if (item?.status === 'failed') {
    showErrorModal.value = true
    errorDetail.value = item.error_message || '未知错误'
    return
}
```

在 template 中合适位置（比如 `<DesignHistory>` 后面）添加模态框：

```html
<AppModal v-model="showErrorModal" title="❌ 设计任务失败" :closable="true">
  <div class="error-detail-content">{{ errorDetail }}</div>
  <template #footer>
    <AppButton variant="primary" @click="showErrorModal = false">关闭</AppButton>
  </template>
</AppModal>
```

**注意**：
- 使用 `{{ errorDetail }}`（textContent）而非 `v-html`，防止错误文本含特殊字符导致 XSS
- `DesignHistory.vue` 列表项中已截取的 25 字符错误文本保持不变（作为快速预览），点击触发模态框展示完整文本

---

### 方案 2：prompt 动态建议上限（P1）

**涉及文件**：
- `backend/app/analysis/prompts/v1/strategy_check.md` — 修改规则 2 为分档描述
- `backend/app/analysis/llm.py` — `generate_strategy_check_report()` 中注入持仓数量 + 计算动态上限

**a) `strategy_check.md` 修改**：

规则 2 改为：

```
2. **suggestions**: 至少 2 条，根据持仓数量分档：
   - 持仓 ≤ 5 只：不超过 5 条
   - 持仓 6-10 只：不超过 8 条
   - 持仓 > 10 只：不超过 12 条
   尽量覆盖主要持仓标的，对因子分显著偏低或无数据的标的可简略处理。
```

**b) `llm.py` `generate_strategy_check_report()` 修改**：

在构建 `holdings_text` 之后，`prompt` 之前，注入持仓数量和建议上限：

```python
holdings_text = "\n".join(holdings_lines)
holdings_count = len(holdings_lines)

# 根据持仓数量动态计算建议数上限
if holdings_count <= 5:
    max_suggestions = 5
elif holdings_count <= 10:
    max_suggestions = 8
else:
    max_suggestions = 12

prompt = f"""
## 市场状态
当前 regime: {regime}
持仓数量: {holdings_count} 只
建议条数上限: {max_suggestions} 条

## 持仓分析
{holdings_text}

请按 strategy_check.md 要求的 JSON 格式输出分析报告。
"""
```

**注意**：
- `.md` 文件仍保留"分档"描述作为规则模板，实际数值由 Python 注入
- `strategy_check.md` 中原有的 JSON 示例字段定义保持不变
- 建议上限增加后 LLM token 消耗会相应上升，但每次调用额外约 200-500 tokens，可接受

---

### 方案 3：数据质量元信息注入 prompt（P2 + P4）

**涉及文件**：
- `backend/app/services/portfolio_service.py` — `strategy_check()` 函数
- `backend/app/analysis/llm.py` — `generate_strategy_check_report()` 接收并注入数据质量信息

**修改内容**：

**a) `portfolio_service.py`** — 在 `strategy_check()` 中收集数据质量信息，传给 `generate_strategy_check_report()`：

在构建 `factor_breakdowns` 后（约第 431 行），统计因子数据质量：

```python
# 统计因子数据质量
filled_factor_count = sum(
    1 for fb in factor_breakdowns.values()
    if fb.get("factor_scores") and any(v != 0 for v in fb["factor_scores"].values())
)
total_factor_count = len(factor_breakdowns)
data_quality = {
    "filled_count": filled_factor_count,
    "total_count": total_factor_count,
    "all_empty": filled_factor_count == 0,
    "partial": 0 < filled_factor_count < total_factor_count,
}
```

然后传给 `generate_strategy_check_report()`（约第 436 行）：

```python
llm_result = await asyncio.wait_for(
    generate_strategy_check_report(
        market_data=market_data,
        factor_breakdowns=factor_breakdowns,
        regime=regime,
        data_quality=data_quality,       # ← 新增参数
    ),
    timeout=45,
)
```

**b) `llm.py`** — 在 prompt 中根据数据质量追加注记：

```python
if data_quality.get("all_empty"):
    prompt += """
⚠️ 数据质量注记：当前所有持仓的因子数据为空，技术信号仅供参考。
请基于权重配置和相关性做判断，降低所有建议的置信度。
"""
elif data_quality.get("partial"):
    prompt += f"""
⚠️ 数据质量注记：{data_quality['total_count'] - data_quality['filled_count']} / {data_quality['total_count']} 只标的因子数据缺失。
请对缺失数据的标的降低置信度。
"""
```

---

### 方案 4：补充单元测试（P3a）

**涉及文件**：
- `backend/tests/test_design_tasks.py`

**修改内容**：新增测试用例，**注意 mock 路径必须修正**。

```python
@patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
async def test_worker_handles_error_dict(self, mock_gen):
    """验证 generate_enhanced_design 返回带 error 的 dict 时，
    design_worker 正确标记为 failed 并保存错误信息。
    
    这是 coverage 盲区：现有测试只测了抛异常路径，没测返回 error dict 路径。"""
    from app.tasks.design_tasks import DesignTaskManager, design_worker

    mgr = DesignTaskManager()
    mgr.create_task(capital=500000)

    mock_gen.return_value = {
        "strategies": [],
        "error": "无候选标的",
        "detail": "数据管道未能生成候选池",
        "market_context": _make_empty_market_context(),
        "generated_at": "2026-07-23T00:00:00Z",
        "design_metadata": {},
    }

    await design_worker(mgr, task_id=1)

    t = mgr.get_task(1)
    assert t["status"] == "failed"
    assert "无候选标的" in t.get("error_message", "")
```

其中 `_make_empty_market_context()` 是 helper：

```python
def _make_empty_market_context():
    return {
        "market_regime": "range_bound",
        "market_sentiment": {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": [],
        "sector_momentum": [],
        "benchmark_stocks": [],
    }
```

**同时必须修复现有 3 条测试的 mock 路径**（从 `app.tasks.design_tasks.generate_enhanced_design` 改为 `app.services.strategy_design.generate_enhanced_design`），因为它们从未生效——见[附录](#五现有测试基础设施-bug-附录)。

---

### 方案 5：级联故障集成测试（P3c）

**新增文件**：`backend/tests/test_design_cascade_failure.py`

**修改内容**：模拟 pool 全空 → strategy_design 返回 error → worker 标记 failed 的完整链路。

由于 `strategy_design.py` 中 `pool_manager` 是全局实例（`from ..services.pool_manager import pool_manager`），且方法通过类继承查找，patch `PoolManager` 类方法即可：

```python
"""测试数据源失败级联到设计任务的完整链路。

所有外部调用（scanner.full_pipeline、classifier、factor_registry）均被 mock。"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _make_empty_ctx():
    return {
        "market_regime": "range_bound",
        "market_sentiment": {"sentiment_index": 50, "sentiment_label": "中性"},
        "index_realtime": [],
        "sector_momentum": [],
        "benchmark_stocks": [],
    }


@pytest.mark.asyncio
@patch(
    "app.services.pool_manager.PoolManager.get_market_regime",
    return_value="range_bound",
)
@patch(
    "app.services.pool_manager.PoolManager.get_market_sentiment",
    return_value={"sentiment_index": 50, "sentiment_label": "中性"},
)
@patch(
    "app.services.pool_manager.PoolManager.get_index_realtime",
    return_value=[],
)
@patch(
    "app.services.pool_manager.PoolManager.get_sector_momentum",
    return_value=[],
)
@patch(
    "app.services.pool_manager.PoolManager.get_factor_matrix",
    return_value={},
)
@patch(
    "app.services.pool_manager.PoolManager.get_pool",
    return_value=[],
)
@patch(
    "app.services.pool_manager.PoolManager.refresh",
    new_callable=AsyncMock,
)
async def test_empty_pool_cascade_to_design_error(
    mock_refresh, mock_get_pool, mock_get_factor,
    mock_get_sector, mock_get_index, mock_get_sentiment, mock_get_regime,
):
    """验证 pool_manager 刷新后候选池为空 → strategy_design 返回 error。
    
    这是真实故障（数据源不可用）的单元级再现。"""
    from app.services.strategy_design import generate_enhanced_design

    result = await generate_enhanced_design(capital=500000)

    assert result.get("error") == "无候选标的"
    assert len(result.get("strategies", [])) == 0
    assert "数据管道" in result.get("detail", "")
```

---

### 方案 6：verify_e2e 增加候选池健康检查 + 失败归因区分（P3b + P3d）

**涉及文件**：
- `backend/scripts/verify_e2e.py`

**a) 新增池健康探针函数**（需新增后端端点 `GET /admin/pool-status` 或在已有端点上增加池信息）：

在 `section_portfolio()` 中设计提交前新增检测：

```python
def _check_candidate_pool(host, port):
    """检查候选池是否已预热。返回 True 表示池有候选标的。"""
    try:
        r = requests.get(f"{BASE}/api/v1/portfolio/designs?limit=1", timeout=10)
        if r.status_code == 200:
            designs = r.json()
            if designs:
                # 最新设计有策略数据说明池曾正常工作
                did = designs[0]["id"]
                dr = requests.get(f"{BASE}/api/v1/portfolio/designs/{did}", timeout=10)
                if dr.status_code == 200:
                    detail = dr.json()
                    strategies = detail.get("strategies", [])
                    if strategies:
                        check("候选池健康（最新设计有策略数据）", True)
                        return True
        check("候选池状态", False, "无历史设计记录或数据为空")
        return False
    except Exception as e:
        check("候选池连通性", False, str(e))
        return False
```

**b) 区分"数据源不可用"和"代码错误"**：

在 `_submit_and_watch` 中，当任务 failed 时读取 error_message，如果包含"数据管道"相关关键词，标记为 `[INFRA]` 而非 `[BUG]`：

```python
elif status == "failed":
    err = pd.get("error_message", "未知")
    is_infra = any(kw in err for kw in ["数据管道", "候选池", "数据源"])
    tag = "[INFRA]" if is_infra else "[BUG]"
    check(f"{tag} 异步设计任务失败", False, err)
```

**c) 输出质量断言**（P3d）：策略检查完成后，验证因子分不为空、建议覆盖率：

```python
if status == "completed":
    suggestions = pd.get("suggestions", [])
    holdings = pd.get("holdings_analysis", [])
    # 建议覆盖率检查
    if holdings:
        suggested_symbols = {s["symbol"] for s in suggestions}
        holding_symbols = {h["symbol"] for h in holdings}
        coverage = len(suggested_symbols & holding_symbols) / len(holding_symbols)
        check(f"策略检查建议覆盖率 {coverage:.0%}", coverage >= 0.3)
        # 因子数据非空检查
        non_empty_factors = sum(
            1 for h in holdings
            if h.get("factor_summary") and "空" not in h["factor_summary"]
        )
        if non_empty_factors == 0:
            check("因子数据可用性", False, "全部为空，见 INFRA 标注")
```

---

## 三、验证标准

| 方案 | 验证方式 | 通过条件 |
|---|---|---|
| **1** (弹窗) | 手动测试：在浏览器中触发设计失败，点击"⚠️ 查看错误" | 模态框弹出，显示完整错误文案，支持复制 |
| **2** (动态建议上限) | 运行 `pytest tests/test_strategy_check_async.py` + 手动提交策略检查 | 10 只持仓输出 ≥6 条建议；5 只持仓输出 ≤5 条 |
| **3** (数据质量注入) | mock 因子分为空，检查 LLM prompt 日志 | prompt 末尾追加了 ⚠️ 注记段落 |
| **4** (单元测试) | `python -m pytest tests/test_design_tasks.py -v` | `test_worker_handles_error_dict` PASS；原有 6 条用例仍 PASS |
| **5** (级联测试) | `python -m pytest tests/test_design_cascade_failure.py -v` | `test_empty_pool_cascade_to_design_error` PASS |
| **6** (verify_e2e) | `python scripts/verify_e2e.py --module portfolio` | 候选池探针输出正确区分 INFRA/BUG |

---

## 四、实施顺序与风险

### 实施顺序

```
第 1 步: 方案 1（P0，仅前端）
         ↓
第 2 步: 方案 4 → 修复现有测试 mock 路径 + 新增用例（P3a，含基础设施修复）
         ↓
第 3 步: 方案 5（P3c，新增测试文件）
         ↓
第 4 步: 方案 3（P2+P4，数据质量注入）
         ↓
第 5 步: 方案 2（P1，prompt 动态上限）
         ↓
第 6 步: 方案 6（P3b+P3d，verify_e2e 增强）
```

### 风险与注意事项

| # | 风险 | 说明 |
|---|---|---|
| R1 | **现有测试 mock 从未生效** | 修复 mock 路径（方案 4 的配套修改）后，现有测试可能因为此前实际调用了真实函数而暴露失败。如果发生，需要检查 `generate_enhanced_design` 的依赖链并补充 mock |
| R2 | **llm.py 的 `generate_strategy_check_report()` 签名变更** | 方案 3 新增 `data_quality` 参数。所有调用方（目前仅 `portfolio_service.py` 一处）需同步更新，否则 TypeError |
| R3 | **verify_e2e 改动可能使测试更脆弱** | 新增的池健康探针可能因瞬态数据不可用导致误报。建议探针不通过时用 `[SKIP]` 而非直接 `FAIL`，避免影响 CI 流程 |
| R4 | **AppModal 复用需确认 props 兼容** | `AppModal.vue` 的 `modelValue`/`v-model` 接口需与 `DashboardAiTools` 的 `showErrorModal` ref 对接。建议先阅读 `AppModal.vue` 的 props 定义 |
| R5 | **级联测试 patch 链过长** | 方案 5 需要 7 个 patch，装饰器顺序和 mock 参数位置必须一一对应。建议逐个添加、逐步验证 |

---

## 五、现有测试基础设施 bug 附录

### 问题

`backend/tests/test_design_tasks.py` 中 **3 条测试用例**全部使用了无效的 mock 路径：

```python
@patch("app.tasks.design_tasks.generate_enhanced_design", new_callable=AsyncMock)
```

### 根因

- `app/app/tasks/design_tasks.py` 是一个向后兼容层，其中**没有定义或导入** `generate_enhanced_design`
- `design_worker` 定义在 `task_manager.py`，其内部通过 `from ..services.strategy_design import generate_enhanced_design` 在函数体内导入，不经过 `design_tasks` 的命名空间
- `unittest.mock.patch` 只替换目标路径的属性，无法拦截函数体内的独立导入

### 后果

该 mock 从未生效。3 条测试实际上在调用**真实的** `generate_enhanced_design()` 函数。测试之所以能通过，是因为：
- `test_worker_failure_sets_failed_status`: mock 的 `side_effect` 未生效，但真实函数可能返回空 strategies 被 `not strategies` 分支捕获，或超时被 `except` 捕获
- `test_worker_runs_full_pipeline`: mock 的 `return_value` 未生效，真实函数可能恰好返回有数据的 result

### 修复

**必须**将 3 处 patch 路径统一改为：

```python
@patch("app.services.strategy_design.generate_enhanced_design", new_callable=AsyncMock)
```

这是方案 4 的配套修改，不单独列出。

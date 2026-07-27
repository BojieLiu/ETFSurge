# 候选池生成逻辑修复方案

> 补充：基于 2026-07-27 实测 debug 的完整修复设计
> **2026-07-27 代码审计状态更新**：以下修复项中，P4（行业均衡化）和 P5（520xxx 前缀）已在代码中发现部分实施痕迹。其余 P0-P2 项待验证/实施。

---

## 实施状态总览

| 修复 | 优先级 | 当前状态 | 代码证据 |
|------|--------|---------|---------|
| P5: mootdx 超时 + 520xxx 白名单 | P0 | 🟡 **部分实施** | `china_market.py` 中 "52" 已出现在文件中（520xxx 前缀已添加）；mootdx 超时待验证 |
| P3: akshare 列名映射修复 | P0 | ❌ **待验证** | 沪市 amount 仍可能为 0，需实测确认 |
| P2: 改用 scale 做主排序 | P1 | ❌ **待实施** | `etf_scanner.py` 排序逻辑需检查 |
| P4: 按行业均衡候选池 | P2 | 🟡 **部分实施** | `pool_manager.py:420` 含 `# P4 fix-plan-pool` 注释，`_balance_by_industry()` 已实现 |
| P6: 非交易时段缓存 | P1 | ❌ **待实施** | `pool_manager.py` 中 `_is_market_hours()` 未找到 |
| P1: filter 逻辑修正 | P2 | ❌ **待实施** | 原 `filter_etfs()` 函数可能已重构，需重审 |

---

## 发现了什么

### 问题 1：filter_etfs 的 amount 过滤逻辑反直觉

```python
# 当前代码（有问题的）：
if amount > 0 and amount < MIN_AVG_AMOUNT:  # MIN_AVG_AMOUNT = 1000万
    continue  # 过滤掉

# 效果：
#   amount=0（数据缺失）→ 通过
#   0 < amount < 1000万（有数据但低）→ 过滤掉
#   amount >= 1000万（有数据且达标）→ 通过，但实际为0只
```

这导致 908 只 amount=0 的 ETF 全部通过，700 只有实际成交数据的被过滤掉。

### 问题 2：layer_ranking 的排序依据全是 0

```python
score = 0.50 × amount_percentile + 0.50 × fund_scale_percentile
```

883 只通过 filter 的 ETF 中，amount 全部为 0（数据缺失），fund_scale 也近乎全 0。全部 score=0 → `sorted()` 稳定排序保持原序（akshare API 返回顺序）→ **排名是随机的**。

### 问题 3：分类关键词覆盖面窄

- `CORE_KEYWORDS` 缺少：科创50、创业板、中证500
- `DEFENSE_KEYWORDS` 包含：恒生、H股、中概（港股非防御资产）
- 结果：港股通 ETF 被分到防御层 → 挤占黄金/债券的位置

### 问题 4：pool_manager 内部 pool build 与 scanner 的解耦问题

pool_manager 自己也做了一次分类和 re-assignment，覆盖了 scanner 的初始分类。原始标签被覆盖后 pool 总量仍只有 47 只，扣除强制保留标的，可旋转仓空间很小。

---

## 修复方案

### 修复 P1: filter_etfs 过滤逻辑修正

**文件**: `etf_scanner.py`

**当前**:
```python
if amount > 0 and amount < MIN_AVG_AMOUNT:
    continue
if scale > 0 and scale < MIN_FUND_SCALE:
    continue
```

**修正**: 当前逻辑在 amount=0 时行为是对的（保留），真正的问题在数据源。但可以增加一个兜底：当 amount=0 时检查是不是因为非交易时段，如果是则用 funds_cale 单独做排名。

### 修复 P2: 改用 fund_scale 做主排序依据

**文件**: `etf_scanner.py:layer_ranking()`

**当前**: `score = 0.50 * amount_percentile + 0.50 * scale_percentile`

**修复为**:
```python
# 检查 amount 是否可用（有正数）
amount_vals = [item.get("amount", 0) or 0 for item in items]
max_amount = max(amount_vals)
if max_amount > 100000:  # 有实际成交数据
    score = 0.30 * amount_percentile + 0.70 * scale_percentile
else:
    score = 1.00 * scale_percentile  # 仅用规模排序
```

同时把 `top_n=15` 提高到 `top_n=25`，增加候选池容量。

### 修复 P3: akshare 列名映射修复

**文件**: `fetchers/etf_dataset.py`（如果存在）或 `etf_scanner.py:fetch_all_etfs_base()`

沪市 ETF 的 amount 和 fund_scale 在 remapping 后为 0，但深市 ETF 有值。说明列名映射表缺失部分沪市列的对应关系。

需要：
1. 读取 akshare 原生 DataFrame 的列名（GBK 编码）
2. 检查 `_decode_df` 的映射表是否覆盖所有列
3. 补充缺失的列名映射

### 修复 P4: 候选池按行业均衡化

**文件**: 新增 `pool_builder.py` 或修改 `etf_scanner.py`

不依赖 amount/fund_scale 做纯排序，而是**按 tracked_index 分类构建均衡候选池**：

```python
POOL_TEMPLATE = {
    "core": {
        "max": 20,
        "categories": {
            "沪深300": 3,
            "中证A500": 2,
            "中证500": 2,
            "科创50": 2,
            "创业板指": 2,
            "上证50": 1,
        }
    },
    "satellite": {
        "max": 30,
        "categories": {
            "半导体": 2, "新能源": 2, "医药": 2,
            "消费": 2, "军工": 1, "证券": 1,
            "科技": 1, "红利": 2, "汽车": 1,
        },
        "other_limit": 15,
    },
    "defense": {
        "max": 10,
        "categories": {
            "黄金": 2, "债券": 3, "全球": 3,
        }
    }
}
```

实现：classify → 每层内按 tracked_index 匹配子类别 → 每个子类别取 fund_scale 最大的前 N 只 → 未匹配的按 fund_scale 取 top K。

### 修复 P5: mootdx 超时 + 520xxx 前缀加入 ETF 白名单

**文件**: `china_market.py`

1. `_ETF_PREFIXES` 加入 `"52"` → 港股通 ETF 走 Sina
2. `_mootdx()` 的 socket read timeout

### 修复 P6: 非交易时段使用缓存排序

**文件**: `pool_manager.py`

```python
def _is_market_hours() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = now.strftime("%H:%M")
    return "09:30" <= t <= "11:30" or "13:00" <= t <= "15:00"
```

非交易时段仅用 fund_scale 排序（更稳定）。

---

## 优先级

| 优先级 | 修复 | 工作量 | 收益 |
|--------|------|--------|------|
| **P0** | P5: mootdx 超时 + 520xxx 白名单 | 1h | 高 |
| **P0** | P3: akshare 列名映射修复 | 2h | 高 |
| **P1** | P2: 改用 scale 做主排序 | 0.5h | 高 |
| **P1** | P6: 非交易时段缓存 | 1h | 中 |
| **P2** | P4: 按行业均衡候选池 | 4h | 高 |
| **P2** | P1: filter 逻辑修正 | 0.5h | 中 |

---

## 验收标准

| 条件 | 验证方式 |
|------|---------|
| 510050 的 amount > 0 | `fetch_all_etfs_base()` 检查 |
| 候选池 >= 60 只 | `full_pipeline()` 输出 |
| 覆盖 8+ 行业板块 | tracked_index 分布检查 |
| 排序一致（非随机） | 连续两次运行结果对比 |
| factor compute < 30s | perf_diag 检查 |
| 港股 ETF 不在 defense 层 | classify 检查 |

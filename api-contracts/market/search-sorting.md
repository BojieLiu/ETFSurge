# API 契约: 搜索排序契约 (Z20)

> 关联方案: `docs/z_fixes_design_v5.3.md` Z20
> 变更类型: 既有端点行为修订（统一分档排序契约：SQL CASE + Python 降级同契约）
> 版本: v2.0

## 1. 概述 / Overview

**功能描述**: 修复搜索接口（`/search`、watchlist 搜索建议）无 `ORDER BY` 导致排序不可复现的问题。定义统一分档排序契约，SQL 层与 Python 降级层严格对齐。

**触发场景**: 
- 前端搜索框输入关键词（WatchlistPanel、MarketSearch）
- verify_e2e 顺序断言

---

## 2. 端点定义 / Endpoints

### 2.1 统一搜索 / Unified Search (行为修订)

```
GET /api/v1/market/search?keyword=<kw>[&market=<A|HK|US|global>][&include_stocks=<bool>]
```

#### 排序契约 / Sorting Contract (Z20 核心)

**分档优先级（高 → 低）**:

| 档位 | 规则 | 说明 |
|------|------|------|
| 1 | **精确代码匹配** | `symbol == keyword`（大小写不敏感） |
| 2 | **代码前缀匹配** | `symbol LIKE keyword%`（如 `510` → `510300`, `510050`） |
| 3 | **精确名称匹配** | `name == keyword` |
| 4 | **名称前缀匹配** | `name LIKE keyword%` |
| 5 | **名称包含匹配** | `name LIKE %keyword%` |
| 6 | **拼音/首字母匹配** | `pinyin LIKE keyword%` 或 `first_letter == keyword.upper()` |

**同档内次序**:
- ETF 优先于个股（同市场内）
- 按 `market` 顺序：`A` → `HK` → `US` → `index` → `commodity`
- 同档同市场同类型内：按 `symbol` 字典序升序

**总条数限制**: `LIMIT 30`（跨市场合并模式），单市场模式 `LIMIT 50`。

#### SQL 实现契约 (SQLite)

```sql
SELECT *, 
  CASE
    WHEN symbol = ? THEN 1                    -- 精确代码
    WHEN symbol LIKE ? || '%' THEN 2          -- 代码前缀
    WHEN name = ? THEN 3                      -- 精确名称
    WHEN name LIKE ? || '%' THEN 4            -- 名称前缀
    WHEN name LIKE '%' || ? || '%' THEN 5     -- 名称包含
    ELSE 6                                    -- 拼音/首字母（需额外列）
  END AS sort_rank,
  CASE asset_type WHEN 'etf' THEN 0 ELSE 1 END AS type_rank,
  market_order(market) AS market_rank,        -- A=1, HK=2, US=3, index=4, commodity=5
  symbol
FROM instruments
WHERE ...匹配条件...
ORDER BY sort_rank, type_rank, market_rank, symbol
LIMIT ?
```

> 注：`market_order` 为 SQL 标量函数或 CASE 表达式实现。

#### Python 降级实现契约 (Z20 同契约)

当走降级路径（如 `get_all_stocks()` 返回列表后 Python 过滤）时，**必须复用相同排序逻辑**：

```python
def _sort_search_results(items: list[dict], keyword: str) -> list[dict]:
    """统一排序契约：SQL 与 Python 行为完全一致。"""
    kw = keyword.strip().upper()
    
    def rank(item):
        sym = item.get("symbol", "").upper()
        name = item.get("name", "")
        asset_type = item.get("asset_type", "")
        market = item.get("market", "")
        
        # 档位 1-5
        if sym == kw:
            sort_rank = 1
        elif sym.startswith(kw):
            sort_rank = 2
        elif name == keyword:
            sort_rank = 3
        elif name.startswith(keyword):
            sort_rank = 4
        elif keyword in name:
            sort_rank = 5
        else:
            # 拼音/首字母匹配（简化：检查首字母）
            first_letters = ''.join([c[0] for c in name.split() if c]).upper() if name else ''
            if first_letters.startswith(kw):
                sort_rank = 6
            else:
                sort_rank = 7
        
        type_rank = 0 if asset_type == "etf" else 1
        market_order = {"A": 1, "HK": 2, "US": 3, "index": 4, "commodity": 5}.get(market, 9)
        
        return (sort_rank, type_rank, market_order, sym)
    
    return sorted(items, key=rank)
```

#### 响应示例 / Response Example (排序验证)

输入：`keyword="510"`

```json
[
  {"symbol": "510050", "name": "华夏上证50ETF", "market": "A", "asset_type": "etf", "type": "etf"},  -- 代码前缀
  {"symbol": "510300", "name": "沪深300ETF", "market": "A", "asset_type": "etf", "type": "etf"},    -- 代码前缀
  {"symbol": "510880", "name": "红利ETF", "market": "A", "asset_type": "etf", "type": "etf"}       -- 代码前缀
]
```

输入：`keyword="茅台"`

```json
[
  {"symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock"}  -- 名称包含
]
```

---

## 3. 适用范围 / Scope

| 端点/功能 | 适用排序契约 |
|-----------|-------------|
| `GET /api/v1/market/search` | ✅ 全模式 |
| `GET /api/v1/market/watchlist` 建议搜索 | ✅ 复用 `_sort_search_results` |
| `market_data_hub.search_etf()` | ✅ 内部复用 |
| `market_data_hub.search_stocks()` | ✅ 内部复用 |

---

## 4. 前后端检查表 / Frontend-Backend Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| 搜索结果按分档排序（代码精确→代码前缀→名称精确→名称前缀→名称包含→拼音） | ☐ | ☐ | 核心契约 |
| 同档内 ETF 优于个股 | ☐ | ☐ | type_rank |
| 同档同类型内按市场序 A→HK→US | ☐ | ☐ | market_rank |
| 最终按 symbol 字典序 | ☐ | ☐ | 确定性 |
| SQL 与 Python 降级排序结果一致 | N/A | ☐ | 单测对比验证 |
| verify_e2e 顺序断言（输入 510/茅台/沪深300） | N/A | ☐ | section_search 新增 |

---

## 5. 测试 / Tests

- 后端单测: `backend/tests/test_z20_search_sort.py`（构造测试数据，验证 SQL 与 Python 排序结果完全一致）
- verify_e2e: `section_search` 模块新增顺序断言用例
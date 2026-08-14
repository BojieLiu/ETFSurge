# News Classification Contract (F22 / F23 / F28) / 资讯分级契约

> **Scope**: 修复 round23 P0-A 投资误导类问题。将资讯 `level`（旧：1-5 既是重要性又是分类，
> 导致利空永不推送、战争被标红为利好）拆分为**两个正交字段**：`category`（极性/类型）+
> `level`（重要性 1-5，单调性）。前端按 `level` 决定推送/筛选，按 `category` 着色。
> 同步修复 F28（`market_data_hub.py` AI 摘要分支 `str(level) in ("重大","利好")` 恒 False）。

## 1. 字段契约 / Field Contract

每条资讯 item（headlines / macro / global / stock / ws 推送）新增/调整字段：

| Field | Type | Description |
|-------|------|-------------|
| `level` | int | **重要性 1-5**（单调性，=旧 importance）。5=紧急/重大, 4=重要(利好/利空/风险均可), 3=中等, 2=一般, 1=其他 |
| `category` | string | **极性/类型**，取值见下。新增字段，前端着色/筛选依据 |
| `stars` | int | 新鲜度维度（1-5），不变 |

`category` 取值：

| category | 含义 | 着色（红涨绿跌 + A股语义） |
|----------|------|---------------------------|
| `major` | 重大/紧急（崩盘/熔断/台风/空袭/袭击/开战） | 深红 `#c0392b` 加粗 |
| `positive` | 利好（降准/涨停/获批/合作…） | 红 `#e64545`（涨=好） |
| `negative` | 利空（暴跌/减持/违约/暴雷…） | 绿 `#1aa260`（跌=坏） |
| `risk` | 地缘/军事/制裁（冲突/军事/干预/制裁/核…） | 橙 `#f59e0b`（警告，非利好红） |
| `neutral` | 提醒/关注（数据/公告/复牌…） | 蓝 `#3b82f6` |
| `other` | 其他 | 灰 `#9ca3af` |

### 分类规则 / Classification rules

- 词表按 **category 优先级** 匹配：`major > risk > positive > negative > neutral > other`。
- `level` 由 category 推导：`major=5, risk/positive/negative=4, neutral=2, other=1`；
  标题含弱化词（或将/可能/传闻/考虑/讨论/有望/据悉/拟）且 level≥4 时降 1 级（不低于 3）。
- **F23 修复**：地缘/军事/制裁词（`冲突/军事/干预/制裁/核…`）归 `risk`（独立，`level=4`），
  **不再**进入 `positive`；`战`/`核` 用显式多字 token（`战争/开战/宣战/军事行动/核冲突…`），
  避免误命中 `挑战`/`战略`/`核查`。

## 2. 后端改动 / Backend

- `fetchers/levistock_fetcher.py`：
  - 新增 `classify_news(title, content) -> (category, level)`（单一入口）。
  - `classify_news_level(title, content)` 保留签名，返回 `level`（重要性），行为对齐本契约。
  - 新增 `classify_news_category(title, content) -> str`。
  - `fetch_cailian_telegraph._make_item` 注入 `category`。
- `fetchers/news_fetcher.py`：`_attach_level` 对所有源（东财/新浪/宏观）注入 `category`。
- `services/market_data_hub.py:1705`：AI 摘要触发条件改为 `int(level) >= 4 or int(stars) >= 4`（重要性判定，非字符串）。

## 3. 前端改动 / Frontend

- `src/utils/newsLevel.js`：新增 `mapNewsCategory(category)` → {color, label}；`isImportant(level)` 保持 `level>=4`。
- `src/components/NewsView.vue`：badge/标题着色改用 `category`（红涨绿跌语义），保留 `level` 重要性筛选。

## 4. 验收 / Acceptance

- T11（方向性偏置可失败）：`战争`/`开战`/`制裁` → `category=risk`（非 `positive`）；`挑战`/`战略` 不误命中 `risk`/`positive`。
- F22：重要 `negative`/`risk` 事件 `level>=4` → 进入 `minLevel>=4` 筛选与推送；不再「利空全隐藏」。
- F28：`level` 为 int 时 AI 摘要分支正确触发（非恒 False）。
- 兼容性：`stars`/`level`/`id`/`sort_time` 字段不变；`category` 为新增 additive 字段。

## 5. 前后端检查表 / Checklist

| Item | Frontend | Backend | Notes |
|------|----------|---------|-------|
| `category` 字段注入（财联社/东财/新浪/宏观） | N/A | ☐ | additive |
| WS 推送携带 `category` | N/A | ☐ | item 已含 |
| 前端按 category 着色 | ☐ | N/A | 红涨绿跌 |
| 推送/筛选按 level>=4 | ☐ | N/A | 利空/风险可进 |
| F28 重要性分支修复 | N/A | ☐ | int 判定 |
| 单测覆盖 T11/F22/F23/F28 | ☐ | ☐ | 负向可失败 |

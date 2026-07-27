# ETF Surge 资讯板块 — 推送阻断分析与修复方案

> 版本: v6 | 日期: 2026-07-26 | **审计更新 — 代码比对**
> 代码审计结果: P0-P1 共 6 项均已在先前阶段实施
> ✅ P0.1 (后端 id) — `news_fetcher.py` line 255: `it["id"] = hashlib.md5(...)`
> ✅ P0.2 (前端 fallback) — `NewsView.vue` line 158: `if (it.id == null) { it.id = ... }`
> ✅ P1.1 (Level 3 中性词移除) — `levistock_fetcher.py` 已迁移至 Level 2
> ✅ P1.2 (冲突关键词清理) — `levistock_fetcher.py` Level 2 已含"反弹"/"拉升"/"回落"等
> ✅ P1.3 (fetch_sina_roll_news) — `news_fetcher.py` line 261 已实现
> ✅ P1.4 (宏观改用新浪) — `fetch_macro_news()` 第一优先级已为新浪财经
> ✅ P1.5 (RSS 重写) — `fetch_global_news()` 已含 RSS 双源 + akshare 降级
> ❌ P2.2 (stars 新鲜度) — 待实施 (Phase 6.1.7)
> ❌ P2.3 (Level 2 精度) — 待实施 (Phase 6.1.7)
> ❌ §8 验证脚本 — 待扩展 (Phase 6.1.8)

---

## 目录

1. [问题总览](#一问题总览)
2. [全链路架构图](#二全链路架构图)
3. [问题 1：WS 推送的资讯无法到达前端（P0）](#三问题-1ws-推送的资讯无法到达前端p0)
4. [问题 2：非财联社数据源覆盖率不足（P1）](#四问题-2非财联社数据源覆盖率不足p1)
5. [问题 3：重要等级划分不科学（P1）](#五问题-3重要等级划分不科学p1)
6. [问题 4：星级冗余且与前端映射断裂（P2）](#六问题-4星级冗余且与前端映射断裂p2)
7. [修复优先级总表与修改清单](#七修复优先级总表与修改清单)
8. [验证方案](#八验证方案)
9. [实施注意事项与已知遗留问题](#九实施注意事项与已知遗留问题)

---

## 一、问题总览

| 编号 | 问题 | 严重度 | 影响 |
|------|------|--------|------|
| 1 | WS 推送的资讯被前端无条件丢弃 | P0 | 资讯模块无实时推送，只有 REST 拉取 |
| 2 | 非财联社数据源（CCTV/百度/东方财富/全球）不稳定，实际只有财联社+RSS 有输出 | P1 | 源覆盖面窄，资讯内容单一 |
| 3 | 等级分类关键词不科学（中性词被标为利空，关键词重叠） | P1 | 等级标签不准确，用户对颜色/级别失去信任 |
| 4 | `stars` 与 `level` 值相同，无独立含义；前端映射也只用到 4 级 | P2 | 星级无实际区分度 |

---

## 二、全链路架构图

```
┌────────────────────────────────────────────────────────────────────┐
│                      后端定时任务 (每30s)                           │
│  refresh_news_cache()   ← APScheduler, coalesce=True              │
│    └─ asyncio.to_thread(fetch_news_headlines)                     │
│         ├─ fetch_cailian_telegraph(15)  ← levistock 库，财联社     │
│         ├─ fetch_macro_news()           ← akshare: CCTV+百度+东方   │
│         └─ fetch_global_news()          ← RSS (MW/CNBC) + akshare  │
│         → _filter_fresh → sort → _dedupe → [:30]                  │
│    └─ for each item:                              越有 id 字段？     │
│       manager.broadcast("news", {type:"news", data: item})  ⇨ WS  │
│                                                                     │
│  REST API (独立路径, 与 WS 共享 fetch_news_headlines 缓存)           │
│  GET /news/headlines ← fetch_news_headlines()                     │
│  GET /news/macro     ← fetch_macro_news()  → 不与 WS 共享 id 逻辑   │
│  GET /news/global    ← fetch_global_news() → 同上                  │
└──────────────────────────┬─────────────────────────────────────────┘
                           │  WebSocket /api/v1/ws/news
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                      前端 NewsView.vue                              │
│  onMounted:                                                         │
│    1. ws.connect()  ← useNewsWS composable                         │
│    2. loadNews()    ← REST GET /news/headlines  ← 正常加载，无id问题 │
│                                                                     │
│  WS onmessage → ws.onmessage handler (useNewsWS.js)                │
│    → msgHandler(msg) → handleNews(msg)                             │
│                                                                     │
│  handleNews(msg)   (NewsView.vue:144)                               │
│    └─ extract item from msg.data or msg                             │
│    └─ if (!item || item.id == null) return     ← 阻塞点！           │
│    └─ if (seenIds.has(item.id)) return          ← 去重              │
│    └─ news.value = [item, ...news.value]         ← 添加到列表头部    │
└────────────────────────────────────────────────────────────────────┘

▸ 推送备份制: _last_titles (后端) 基于 title 去重, seenIds (前端) 基于 id 去重
▸ 两个去重机制独立运作，互相兼容
```

---

## 三、问题 1：WS 推送的资讯无法到达前端（P0）

### 3.1 现象

- 页面打开时通过 REST API 能正常加载新闻列表
- WS 连接状态显示「已连接」（绿色圆点）
- 但实时推送的新闻**永远不会出现在列表中**
- 后端日志有 `资讯广播完成: N 条`，但前端无响应

### 3.2 根因

**后端所有新闻数据源均不设置 `id` 字段，而前端 `handleNews()` 强制要求 `id` 非空。**

后端 `fetch_cailian_telegraph()` 返回的条目格式（`levistock_fetcher.py` 第 129-136 行）：

```python
{
    "title": "快讯标题",
    "content": "详情内容",
    "time": "2026-07-22 10:30:00",
    "source": "财联社",
    "level": 4,
    "stars": 4,
    # 没有 id！
}
```

其他子提取函数（`fetch_macro_news`, `fetch_global_news`）同样不设 `id`。`fetch_news_headlines()` 只在末尾做 dedupe、sort、截断，也不设 `id`。

前端的阻断逻辑（`NewsView.vue` 第 144-150 行）：

```js
function handleNews(msg) {
  const item = msg && msg.data ? msg.data : msg
  if (!item || item.id == null) return    // ← undefined == null → true → 丢弃！
  if (seenIds.value.has(item.id)) return
  seenIds.value.add(item.id)
  news.value = [item, ...news.value]
}
```

JS 中 `undefined == null` 为 `true`，而所有后端推送的 item 都没有 `id`，所以 `item.id` 是 `undefined`，条件成立，**全部推送被无条件丢弃**。

### 3.3 修复方案

#### 3.3.1 后端：在 `fetch_news_headlines()` 末尾分配 `id`（P0 必须）

在 `news_fetcher.py` 的 `fetch_news_headlines()` 中，经过 _dedupe 和 `[:30]` 截断之后、`return` 之前，为每条资讯生成稳定的 `id`：

```python
import hashlib

# 在 items = _dedupe(items)[:30] 之后，return 之前：
for it in items:
    dedup_key = f"{it.get('time', '')}_{it.get('title', '')}"
    it["id"] = hashlib.md5(dedup_key.encode()).hexdigest()[:12]
return items
```

**设计决策**：

- 使用 `time + title` 哈希以保证**同一内容 id 稳定**：相同新闻在不同调度周期中拥有相同 id，前端 `seenIds` 可正确去重
- 前 12 位（48 bit）足以避免碰撞；多源去重已验证
- `id` 放在 dedupe/cut **之后**以避免对已被 dedup 丢弃的条目不必要地分配 id
- `id` 在 `_cached` 包装器内部，所以缓存命中时也会包含 id

**影响范围**：仅 `fetch_news_headlines()` 路径（即 WS 推送 + REST `/news/headlines`）获得 id。REST 端点 `/news/macro` 和 `/news/global` 直接调用 `fetch_macro_news()` 和 `fetch_global_news()`，**不会获得 id**。但这不影响核心链路，因为：
- WS 推送只走 `fetch_news_headlines()` → 有 id → WS 推送正常工作
- `/news/headlines` 也走 `fetch_news_headlines()` → 同样有 id → REST 正常
- `/news/macro` 和 `/news/global` 在前端**作为独立页面/面板使用**，不通过 WS 推送

#### 3.3.2 前端：`handleNews()` 增加无 `id` fallback（P0 必须，双重保障）

```js
function handleNews(msg) {
  const item = msg && msg.data ? msg.data : msg
  if (!item || !item.title) return

  // 后端若缺 id（如 `/news/macro` 直接推送场景），用 time+title 降级生成
  if (item.id == null) {
    item.id = `${item.time || Date.now()}_${item.title}`
  }
  if (seenIds.value.has(item.id)) return
  seenIds.value.add(item.id)
  news.value = [item, ...news.value]
}
```

**变更点**：
- `!item.id == null` → `!item.title`：更健壮的 guard，因为 title 是所有数据源普遍存在的字段
- 新增 `id == null` 降级逻辑，用 `time + title`（或 `Date.now() + title`）生成临时 id

---

## 四、问题 2：非财联社数据源覆盖率不足（P1）

### 4.1 现象

- 实际收到的资讯主要来自财联社快讯和 RSS（MarketWatch/CNBC）
- CCTV、百度宏观、东方财富宏观、akshare 全球等源几乎没有数据
- 宏观新闻退化为财联社内容的简单重复（fallback 机制导致）

### 4.2 根因

**akshare 是瓶颈**。`fetch_macro_news()` 的 3 个子源（CCTV/百度/东方财富宏观）**100% 依赖 akshare**。`_ak()` 包装器（`news_fetcher.py` 第 31-44 行）：

```python
def _ak(fn, timeout: int = _AK_TIMEOUT) -> list[dict[str, Any]]:
    def _p():
        with no_proxy():
            import akshare as ak
            df = fn(ak)
        _decode_df(df)
        return df.to_dict(orient="records")
    result = run_in_thread(_p, timeout=timeout)
    return result or []
```

akshare 不稳定有其结构性原因：

| 问题 | 说明 |
|------|------|
| **多层线程叠加** | `_ak()` 用 `run_in_thread` 提交到共享线程池 → akshare 内部又可能用 `requests` 或 `threading` → 多线程交织增加不确定性 |
| **依赖底层源稳定性** | akshare 本身只是对 HTTP 接口的封装（如 CCTV/百度），不改变源自身的稳定性。**绕过 akshare 直接 HTTP 调用更可靠** |
| **解码开销** | `_decode_df()` 处理 latin1 编码乱码 → `to_dict()` 转换 → 每步都可能异常 |
| **`no_proxy()` 范围** | `with no_proxy()` 包裹整块，但 akshare 内部有自己的会话管理，可能不生效 |

**核心结论**：解决方案不是"让 akshare 更快"，而是**用不依赖 akshare 的直接 HTTP 源替代它**。

### 4.3 数据源调研

#### 4.3.1 新浪财经滚动新闻 API（推荐，替代 akshare）

**接口**：

```
GET https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=20
```

| 属性 | 值 |
|------|-----|
| **URL** | `https://feed.mix.sina.com.cn/api/roll/get` |
| **参数** | `pageid=153`（新浪财经）, `lid=2509`（滚动要闻）, `num=20`（条数） |
| **返回格式** | JSON，`result.data[]` 含 `title` / `intro` / `ctime` / `media_name` |
| **稳定性** | **极高**——新浪自身首页使用该接口，改了就崩自己网站 |
| **认证** | 无需 API key，无需注册，完全免费 |
| **响应速度** | 实测 ~0.3s |
| **覆盖范围** | 国内宏观、政策、市场要闻，每日数百条更新 |

**已在项目中使用**：`china_market.py` 已使用 `hq.sinajs.cn`（新浪实时行情接口），新增 Sina 新闻接口与现有代码风格一致。

#### 4.3.2 东方财富直接 HTTP（备选）

akshare 的 `news_economic_cls()` 底层也是封装东方财富的 HTTP 接口，可直接调用避免 akshare 开销。但新浪源已足够覆盖需求，**EM 作为二级备选**。

#### 4.3.3 扩展 RSS 源

| 源 | 地址 | 说明 |
|----|------|------|
| ❌ 新华网财经 | 已下线 | 不可用 |
| ❌ 人民网财经 | 已下线 | 不可用 |
| ✅ MarketWatch | `https://feeds.content.dowjones.io/public/rss/mw_top_stories` | 已在使用 |
| ✅ CNBC | `https://www.cnbc.com/id/100003114/device/rss/rss.html` | 已在使用 |

国内官方源 RSS 已被陆续关闭，RSS 层面保持现有 MW + CNBC 两个即可。

### 4.4 修复方案

#### 4.4.1 新增 `fetch_sina_roll_news()`（P1 必须）

在 `news_fetcher.py` 中新增函数。在文件顶部已有 `import` 区域新增 `import requests`（如已存在则跳过）。函数体使用直接 HTTP GET 调用新浪 API：

```python
# ——————————————————————
# 文件顶部已有 import 区域新增：
import requests
# ——————————————————————

def fetch_sina_roll_news(limit: int = 15) -> list[dict[str, Any]]:
    """新浪财经滚动新闻（免费 JSON API，非 akshare，极稳定）。

    接口: https://feed.mix.sina.com.cn/api/roll/get
    pageid=153 → 新浪财经, lid=2509 → 滚动要闻
    无认证，JSON 返回，0.3s 稳定响应。
    """
    def _p():
        try:
            with no_proxy():
                s = requests.Session()
                s.trust_env = False
                s.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
                    "Referer": "https://finance.sina.com.cn",
                })
                url = f"https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num={limit}"
                r = s.get(url, timeout=5)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            logger.warning("[news_sina] 新浪财经 API 请求失败: %s", e)
            return []

        if not isinstance(data, dict) or "result" not in data:
            logger.warning("[news_sina] 新浪财经返回格式异常")
            return []

        items = []
        for entry in (data.get("result") or {}).get("data") or []:
            items.append({
                "title": entry.get("title", ""),
                "content": entry.get("intro", ""),
                "time": entry.get("ctime", ""),
                "source": entry.get("media_name", "新浪财经"),
            })
        return _attach_level(items)
    return _cached("sina_roll", _p, "news_headlines")
```

**设计要点**：
- 使用 `no_proxy()` + `requests.Session`，与 `china_market.py` 的 `_session()` 模式一致
- 5s 超时，远快于 akshare 的 8-15s
- 返回后经 `_attach_level()` 打标（与现有流程一致）
- 通过 `_cached` 包装，TTL 120s
- **⚠️ 时间格式风险**：新浪 API 返回的 `ctime` 可能为 `"YYYY-M-D HH:MM:SS"`（月份/日期无前导零）。`_parse_time()` 的正则要求 `\d{2}` 精确 2 位。若遇到该格式，`_normalize_time` 会跳过该字段。不影响程序运行，仅导致该条目无法按时间排序和过滤。建议实施后观察新浪返回的时间格式，必要时增强 `_parse_time()` 兼容单数字月/日。

**`_attach_level` 行号引用**：`news_fetcher.py` 第 195-204 行。

#### 4.4.2 重构 `fetch_macro_news()` 降级链（P1 必须）

**旧**：3 个 akshare 源 → fallback 到财联社
**新**：

```
优先级 1: fetch_sina_roll_news(15)   ← 新增，稳定 HTTP JSON
优先级 2: _ak(lambda ak: ak.news_economic_cls())  ← akshare 东方财富（降级）
优先级 3: fetch_cailian_telegraph(5)  ← 财联社兜底（不改）
```

```python
def fetch_macro_news() -> list[dict[str, Any]]:
    def _p():
        items: list[dict[str, Any]] = []
        # 优先级 1: 新浪财经滚动新闻（直接 HTTP，稳定）
        try:
            sina = fetch_sina_roll_news(15)
            if sina:
                logger.info("[news] 新浪财经返回 %d 条", len(sina))
                items += sina
            else:
                logger.warning("[news] 新浪财经返回空")
        except Exception as e:
            logger.warning("[news] 新浪财经异常: %s", e)

        # 优先级 2: akshare 东方财富宏观（降级）
        if not items:
            try:
                em = _ak(lambda ak: ak.news_economic_cls(), timeout=10)
                if em:
                    logger.info("[news] 东方财富宏观返回 %d 条", len(em))
                    items += em
                else:
                    logger.warning("[news] 东方财富宏观返回空")
            except Exception as e:
                logger.warning("[news] 东方财富宏观异常: %s", e)

        # 优先级 3: 财联社兜底
        if not items:
            items = fetch_cailian_telegraph(5)
        return _attach_level(_dedupe(items)[:25])
    return _cached("macro", _p, "news_macro")
```

**变更要点**：
- 删除了 `ak.news_cctv()` 和 `ak.news_economic_baidu()`（被新浪源替代）
- `ak.news_economic_cls()` 降级为第二优先级，仅在无新浪数据时触发
- 保留了财联社兜底
- 新增详细的 logger 信息

#### 4.4.3 重构 `fetch_global_news()` 降级链（P1 推荐）

**旧**：2 个 RSS → akshare global
**新**：

```
优先级 1: RSS (MarketWatch, CNBC)   ← 不变
优先级 2: _ak(stock_info_global_cls)  ← akshare 全球（降级）
```

```python
def fetch_global_news() -> list[dict[str, Any]]:
    def _p():
        items: list[dict[str, Any]] = []
        feeds = [
            "https://feeds.content.dowjones.io/public/rss/mw_top_stories",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
        ]
        for f in feeds:
            d = _safe(lambda: feedparser.parse(f), 8)
            if d:
                for e in (d.entries or [])[:8]:
                    items.append({
                        "title": e.get("title", ""),
                        "source": "RSS",
                        "time": e.get("published", ""),
                    })
        if not items:
            items += _ak(lambda ak: ak.stock_info_global_cls())
        return _attach_level(_dedupe(items)[:25])
    return _cached("global", _p, "news_global")
```

#### 4.4.4 保留 akshare 但明确降级

akshare 不再作为主要数据源，仅保留在两个场景：

| 场景 | 角色 | 优先级 |
|------|------|--------|
| `fetch_macro_news()` | 东方财富宏观（备选） | 第二优先级 |
| `fetch_global_news()` | 全球信息（兜底） | 第二优先级 |
| `fetch_stock_news()` | 个股新闻（原有） | 不变 |
| `fetch_research_reports()` | 研报（原有） | 不变 |

`_AK_TIMEOUT` 仍可从 8s 放宽到 15s 以减少超时概率，但由于 akshare 已降级，**即使超时也不会影响主数据流**。

**调用链耗时对比**：

| 场景 | 改动前 | 改动后 |
|------|--------|--------|
| `fetch_macro_news()` 正常 | 3 × akshare（≤24s） | 1 × 新浪 HTTP（~0.3s） |
| `fetch_macro_news()` 降级 | 财联社兜底（~0.4s） | akshare EM → 财联社（~10s） |
| `fetch_global_news()` 正常 | 2 × RSS + akshare（≤24s） | 2 × RSS（≤16s） |
| `fetch_global_news()` 降级 | akshare（8s） | akshare（15s，降级） |

---

## 五、问题 3：重要等级划分不科学（P1）

### 5.1 现象

- 大量普通公告被标记为 Level 3（关注），导致高等级标签区分度降低
- 部分利好/利空关键词互相冲突
- 中性词汇被误归为负面

### 5.2 根因

分类函数 `classify_news_level()` 位于 `levistock_fetcher.py`，使用**纯关键词匹配**，从 Level 5 降到 Level 2，返回首个命中的级别。`_LEVEL_KEYWORDS` 定义（`levistock_fetcher.py` 第 32-88 行）：

```python
_LEVEL_KEYWORDS: dict[int, tuple[str, ...]] = {
    5: ("重大", "紧急", "突发", "重磅", "urgent", "特急",
        "崩盘", "熔断", "停牌", "退市", "破产", "违约",
        "制裁", "战争", "军事行动", "恐怖袭击", "地震", "疫情",
        "暂停交易", "紧急停牌"),
    4: ("利好", "上调", "降准", "降息", "positive", "超预期",
        "大涨", "涨停", "创新高", "突破", "新高",
        "大幅增长", "大幅上升", "飙升", "暴涨", "证监会", "央行", "国务院",
        "发改委", "财政部", "商务部",
        "获批", "核准", "签署", "投产", "量产", "落地",
        "净买入", "回购", "增持", "加仓",
        "反弹", "拉升", "走强", "牛市", "看涨",
        "降费", "减税", "补贴", "扶持", "放宽",
        "经济复苏", "扩张", "加速", "回暖",
        "降息预期", "量化宽松"),
    3: ("利空", "下调", "暴跌", "negative",
        "大跌", "跌停", "创新低", "跌破", "新低",
        "减持", "净卖出", "流出", "出逃", "召开", "会议", "讲话", "发言",
        "下滑", "萎缩", "放缓", "减速", "回落",
        "暂停", "终止", "取消", "撤回", "中止",
        "违规", "处罚", "调查", "立案", "警示", "通报批评",
        "亏损", "下降", "熊市", "低迷", "疲软",
        "做空", "抛售", "空头", "撤离",
        "加息", "缩表", "收紧",
        "暴雷", "爆雷", "踩雷", "违约",
        # ⚠️ 注意: "回落" 在此 Level 3, "反弹"/"拉升" 在 Level 4
        ),
    2: ("提醒", "关注", "注意", "风险", "watch",
        "公告", "发布", "通知", "公布", "披露", "预告",
        "展望", "提示", "预警",
        "政策", "规则", "办法", "意见", "方案", "措施",
        "调整", "变化", "影响", "改革",
        "交易所", "银保监会", "金管局",
        "数据", "CPI", "PMI", "GDP", "社融", "信贷",
        "指数", "板块", "行业", "赛道",
        "开盘", "收盘", "盘中", "尾盘", "午盘",
        "港股", "美股", "外围市场", "欧股", "日股",
        "审议", "通过", "获批", "批复",           # ⚠️ "获批" 在 Level 4 也有！
        "逆回购", "MLF", "LPR", "SLF", "再贷款",
        "北向资金", "主力资金", "融资", "融券",
        "IPO", "上市", "新股",
        # ... (更多, 总计 ~60+ 词)
        ),
}
```

**具体问题**：

| 问题 | 说明 | 严重度 |
|------|------|--------|
| "召开"、"会议"、"讲话"、"发言" 在 Level 3 | 中性政府/公司公告词，无负面含义，却被打上"关注"标签（橙底） | **高** |
| "获批" 同时出现在 Level 4 和 Level 2 | 降序匹配时 Level 4 优先，不产生 bug，但语义不纯净 | 中 |
| "反弹"/"拉升" 偏利好置于 Level 4，"回落" 偏利空置于 Level 3 | 三者都是价格走势词，语境模糊却被分配到相反分类 | 中 |
| Level 2 关键词过于宽泛，~60+ 词 | 包含 "开盘/收盘/盘中" 等时间描述，不反映重要性 | 低 |

### 5.3 修复方案

#### 5.3.1 移除 Level 3 中的中性词（P1 必须）

从 `_LEVEL_KEYWORDS[3]` 的 tuple 中删除：

```python
# 要删除的 4 个词：
"召开", "会议", "讲话", "发言"
```

**理由**：这些词出现在标题中仅表示某方发布了观点或举行了会议，不代表利空。保留 "违规"、"处罚"、"立案"、"亏损"、"暴雷"、"做空"、"加息" 等真正负面词。

**影响范围**：`_attach_level()` 是兜底逻辑，仅对**没有预置 level 的条目**（主要来自 `fetch_macro_news` 和 `fetch_global_news`）做关键词匹配。财联社源的 level 由 `fetch_cailian_telegraph()` 内部的 `_level_of()` 设置，不受关键词表变更影响。

#### 5.3.2 清理冲突关键词（P1 推荐）

- "获批"：仅保留在 Level 4（利好/正面），从 Level 2 删除
- "反弹"、"拉升"、"回落"：从 Level 4（反弹/拉升）和 Level 3（回落）中移除，统一移至 Level 2（异动/提醒）

**理由**："反弹" 既可能是上涨利好（从底部反弹），也可能只是短暂波动，"拉升" 和 "回落" 同理——它们更适合放在 Level 2 做中性提醒。

#### 5.3.3 调整 Level 2 精度（P2 可选）

将 "开盘"、"收盘"、"盘中"、"尾盘"、"午盘" 等纯时间描述词从 Level 2 下移到 Level 1（无分类），因为它们仅表示交易时段，不反映资讯重要性。

---

## 六、问题 4：星级冗余且与前端映射断裂（P2）

### 6.1 现象

- 后端 `stars = level`（两者值相同）
- 前端 `mapNewsLevel()` 只渲染到 4 星，5 星从未出现
- 星级作为独立视觉维度没有实际含义

### 6.2 根因

赋值位置（`levistock_fetcher.py` 第 134-135 行 + `news_fetcher.py` 第 201-203 行）：

```python
# levistock_fetcher.py: fetch_cailian_telegraph 内
out.append({
    "title": title, "content": content, "time": time,
    "source": "财联社", "level": level, "stars": level,  # ← stars = level
})

# news_fetcher.py: _attach_level 内
it["level"] = level
it["stars"] = level  # ← 同样的值
```

前端映射（`newsLevel.js`）：

```js
export function mapNewsLevel(level) {
  if (lvl >= 4) return { color: 'red', stars: '★★★★', label: '重要' }
  if (lvl === 3) return { color: 'orange', stars: '★★★', label: '关注' }
  if (lvl === 2) return { color: 'blue', stars: '★★', label: '一般' }
  return { color: 'gray', stars: '★', label: '普通' }
}
```

- `stars` 是 `level` 的镜像，没有任何额外信息
- 前端 `mapNewsLevel` 将 level 4+ 统一映射为 4 星，5 星不可达
- **后端 `stars` 字段在前端未被消费**：前端 `NewsView.vue` 中星级显示调用 `mapNewsLevel(item.level)` 而非 `item.stars`，`stars` 字段是完全的冗余数据

### 6.3 修复方案

#### 6.3.1 让 `stars` 反映时间新鲜度（P2 推荐）

在 `news_fetcher.py` 中新增 `_compute_stars()` 函数，并在 `_attach_level()` 和 `fetch_cailian_telegraph()` 的 stars 赋值处调用：

```python
def _compute_stars(level: int, time_str: str) -> int:
    """stars = 重要性 + 时间新鲜度，上限 5 星"""
    hours_ago = 999
    if time_str:
        try:
            dt = datetime.strptime(time_str[:19], "%Y-%m-%d %H:%M:%S")
            hours_ago = (datetime.now() - dt).total_seconds() / 3600
        except (ValueError, IndexError):
            pass
    freshness = 1 if hours_ago < 2 else 0   # 2 小时内 +1 星
    return min(5, level + freshness)
```

- 重要性高且时效性好的新闻获得更高星级（最多 5 星）
- 2 小时以上的新闻 `stars = level`，无新鲜度加成

#### 6.3.2 或简化：只保留 `level`，删除 `stars` 字段（P2 备选）

如果不想增加计算复杂度，可直接删除 `stars` 字段。前端所有视觉信息已由 `mapNewsLevel(level)` 独立生成，`stars` 字段对前端是冗余的。

---

## 七、修复优先级总表与修改清单

### 7.1 优先级总表

| 优先级 | 修复项 | 涉及文件 | 修改量 | 风险 | 依赖 |
|--------|--------|---------|--------|------|------|
| **P0** | 后端 `fetch_news_headlines()` 加 `id` | `backend/app/fetchers/news_fetcher.py` | +3 行 | 低 | 无 |
| **P0** | 前端 `handleNews()` 加无 `id` fallback | `frontend/src/components/NewsView.vue` | +3 行 | 低 | 无 |
| **P1** | 移除 Level 3 中性词 | `backend/app/fetchers/levistock_fetcher.py` | 删 4 词 | 低 | 无 |
| **P1** | 清理冲突关键词 | `backend/app/fetchers/levistock_fetcher.py` | 调整 3 词 | 低 | 无 |
| **P1** | 新增 `fetch_sina_roll_news()` | `backend/app/fetchers/news_fetcher.py` | +40 行 | 低 | 无 |
| **P1** | 重写 `fetch_macro_news()` 降级链 | `backend/app/fetchers/news_fetcher.py` | -CCTV/百度, +新浪 | 低 | P1.3 |
| **P1** | 重写 `fetch_global_news()` 降级链 | `backend/app/fetchers/news_fetcher.py` | 调整 +5 行 | 低 | 无 |
| **P2** | 放宽 `_AK_TIMEOUT` 8s→15s（可选） | `backend/app/fetchers/news_fetcher.py` | 改 1 常量 | 低 | akshare 已降级 |
| **P2** | `stars` 引入时间新鲜度 | `backend/app/fetchers/news_fetcher.py` + `levistock_fetcher.py` | +10 行 | 低 | 无 |
| **P2** | 调整 Level 2 精度 | `backend/app/fetchers/levistock_fetcher.py` | 删 ~5 词 | 低 | 无 |

**推荐实施顺序**：P0 两处 → P1 五处（注意 P1.3 须在 P1.4 之前） → P2 三处

### 7.2 详细修改清单

#### P0.1 — `backend/app/fetchers/news_fetcher.py`

**位置**：`fetch_news_headlines()` 内部，`_dedupe(items)[:30]` 之后、`return` 之前

**改动**：
```python
# 新增 import（文件顶部）
import hashlib

# 函数体内，替换 return _dedupe(items)[:30] 为：
items = _dedupe(items)[:30]
for it in items:
    dedup_key = f"{it.get('time', '')}_{it.get('title', '')}"
    it["id"] = hashlib.md5(dedup_key.encode()).hexdigest()[:12]
return items
```

#### P0.2 — `frontend/src/components/NewsView.vue`

**位置**：`handleNews(msg)` 函数

**改动**：将 `if (!item || item.id == null) return` 替换为更健壮的 `if (!item || !item.title) return` + 降级 id 生成

#### P1.1 — `backend/app/fetchers/levistock_fetcher.py`

**位置**：`_LEVEL_KEYWORDS[3]` tuple

**改动**：删除 `"召开"`, `"会议"`, `"讲话"`, `"发言"` 四个词

#### P1.2 — `backend/app/fetchers/levistock_fetcher.py`

**位置**：`_LEVEL_KEYWORDS[4]` 和 `_LEVEL_KEYWORDS[2]`

**改动**：
- 从 `_LEVEL_KEYWORDS[4]` 中删除 `"反弹"`, `"拉升"`，从 `_LEVEL_KEYWORDS[3]` 中删除 `"回落"`
- 将这三个词添加到 `_LEVEL_KEYWORDS[2]`（异动/提醒）
- 从 `_LEVEL_KEYWORDS[2]` 中删除 `"获批"`（仅保留在 Level 4）

#### P1.3 — `backend/app/fetchers/news_fetcher.py`（新增源）

**位置**：
1. 文件顶部 `import` 区域新增 `import requests`
2. 文件末尾附近新增函数 `fetch_sina_roll_news()`

**改动**：文件顶部新增 `import requests`，新增 ~40 行函数。使用直接 HTTP GET 调用新浪财经滚动新闻接口，见[第 4.4.1 节](#441-新增-fetch_sina_roll_newsp1-必须)完整代码。

**关键点**：
- 使用 `requests.Session` + `no_proxy()`，与 `china_market.py` 的 `_session()` 模式一致
- 5s 超时，带 try/except 和 `raise_for_status()` 错误检测
- JSON 格式校验：`isinstance(data, dict)` + `"result" in data`
- 返回后经 `_attach_level()` 打标
- 通过 `_cached("sina_roll", _p, "news_headlines")` 缓存，TTL 120s

#### P1.4 — `backend/app/fetchers/news_fetcher.py`（重写 `fetch_macro_news()`）

**位置**：`fetch_macro_news()` 函数体

**改动**：替换为新的三级降级链，见[第 4.4.2 节](#442-重构-fetch_macro_news-降级链p1-必须)完整代码。

**变更记录**：
- 删除：`ak.news_cctv()` 调用
- 删除：`ak.news_economic_baidu()` 调用
- 新增：`fetch_sina_roll_news(15)` 作为第一优先级
- 保留：`ak.news_economic_cls()` 降级到第二优先级
- 保留：财联社兜底（第三优先级）
- 新增：每个源独立的 try/except + logger 日志

#### P1.5 — `backend/app/fetchers/news_fetcher.py`（重写 `fetch_global_news()`）

**位置**：`fetch_global_news()` 函数体

**改动**：结构微调，保持 2 级 RSS + akshare 降级链，见[第 4.4.3 节](#443-重构-fetch_global_news-降级链p1-推荐)完整代码。

#### P2.1 — `backend/app/fetchers/news_fetcher.py`（放宽 akshare 超时，可选）

**位置**：模块级常量

**改动**：`_AK_TIMEOUT = 8` → `_AK_TIMEOUT = 15`

**说明**：akshare 已降级为备选，不再关键路径。`fetch_macro_news()` 已显式传 `timeout=10`。保留 8s 可让故障快速失败，**此项为可选优化**。

#### P2.2 — `backend/app/fetchers/news_fetcher.py` + `levistock_fetcher.py`（stars 时间新鲜度）

**位置**：
- `news_fetcher.py`：在 `_attach_level()` 上方新增 `_compute_stars()` 函数
- `levistock_fetcher.py`：在 `fetch_cailian_telegraph()` 的 stars 赋值处调用 `_compute_stars()`

**改动**：新增 `_compute_stars(level, time_str)` 函数，在 _attach_level 和 fetch_cailian_telegraph 的 `stars = level` 处改为 `stars = _compute_stars(level, time)`。详见[第 6.3.1 节](#631-让-stars-反映时间新鲜度p2-推荐)。

#### P2.3 — `backend/app/fetchers/levistock_fetcher.py`（调整 Level 2 精度）

**位置**：`_LEVEL_KEYWORDS[2]` tuple

**改动**：将 `"开盘"`, `"收盘"`, `"盘中"`, `"尾盘"`, `"午盘"` 从 Level 2 下移至 Level 1（无分类）。详见[第 5.3.3 节](#533-调整-level-2-精度p2-可选)。

---

## 八、验证方案

### 8.1 后端验证

```bash
# 1. 确认 id 字段存在
curl -s http://localhost:8000/api/v1/news/headlines | python -m json.tool | head -30
# 每条应包含 "id": "<12-char hex>"

# 2. 确认新浪源正常工作（直接测试）
curl -s "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&num=5" | python -c "import sys,json; d=json.load(sys.stdin); print(f'新浪源可用: {len(d[\"result\"][\"data\"])} 条')"

# 3. 确认 log 中源明细
# 启动后端后，观察日志:
#   [news] 新浪财经返回 N 条
#   [news] 东方财富宏观返回 N 条（降级时出现）

# 4. E2E 验证
cd backend && python scripts/verify_e2e.py --module news

# 5. WS 链路验证（需 websocat/wscat）
wscat -c ws://localhost:8000/api/v1/ws/news
# 等待 ≤30s，应收到: {"type":"news", "data": {"id":"abc123","title":"...",...}}
```

### 8.2 前端验证

| 检查项 | 方法 | 预期 |
|--------|------|------|
| 连接状态 | 打开 NewsView | 绿色「已连接」 |
| WS 推送 | 等待 30s | 新条目在列表顶部出现 |
| 级别颜色 | 查看不同 level 的条目 | Level 4=红, Level 3=橙, Level 2=蓝, Level 1=灰 |
| 重要提醒 | 进入页面 | Level 4+ 条目触发 toast |
| 去重 | 同一条新闻不会重复出现 | seenIds 有效 |
| REST 加载 | 刷新页面 | 初始列表正常加载 |

### 8.3 单元测试更新

| 测试文件 | 变更 | 类型 |
|----------|------|------|
| `frontend/src/composables/useNewsWS.spec.js` | 无需修改 | — |
| `frontend/src/utils/newsLevel.spec.js` | 若调整 mapNewsLevel 映射，需更新用例 | 可选 |
| `backend/tests/` | 建议新增用例：验证 `fetch_news_headlines` 返回的每一条都含 `id` | 可选 |

---

## 九、实施注意事项与已知遗留问题

### 9.1 前后端同步部署

P0 修复需要后端和前端同步改，单改一端无效。推荐在同一次部署中完成两端修改。

**部署顺序**：
1. 同时部署后端（加 `id`）和前端（加 fallback）
2. 先上线前端再上线后端是安全的（fallback id 生效）
3. 先上线后端再上线前端也是安全的（id 字段存在，前端 `if (item.id == null)` 不触发）
4. **最坏情况**：忘记部署前端，仅有后端上线——WS 推送仍然被阻塞，但 REST 正常。不会崩溃或报错。

### 9.2 关键词修改的影响范围

`_attach_level()` 是兜底逻辑，仅对**没有预置 `level` 字段的条目**起作用：

```
财联社条目   → fetch_cailian_telegraph() 内已设 level/keywords 不涉及
新浪财经     → fetch_sina_roll_news() 内无预置 level → _attach_level → 受影响
东方财富宏   → akshare 返回无预置 level → _attach_level → 受影响
RSS 条目     → fetch_global_news() 内无预置 level → _attach_level → 受影响
akshare 全球  → 同上
```

修改关键词主要影响非财联社源的分类。从 Level 3 移除中性词后，部分公告类新闻会从 Level 3（关注）降到 Level 2 或 Level 1，**这是期望行为**——让真正重要的新闻获得更高显示优先级。

### 9.3 `_last_titles` vs `seenIds` 双去重机制

后端 `news_refresh.py` 的 `_last_titles`（基于 title）和前端的 `seenIds`（基于 id）是独立的去重机制：

```
后端 _last_titles:
  作用: 决定「哪些条目需要广播」（只广播新 title）
  粒度: title 字符串
  生命周期: 进程内，随进程重启重置

前端 seenIds:
  作用: 决定「哪些条目加入 UI 列表」（防止重复渲染）
  粒度: id 字符串
  生命周期: 页面 session 内，随页面刷新重置
```

加入 `id` 后，两者一致。如果某条新闻的 title 改变了但 id 稳定（不可能，因为 id = hash(time+title)），两个去重机制都会正确工作。

### 9.4 `seenIds` 潜在内存增长

`seenIds` 是 `Set<string>`，在长时间运行（数小时）的页面 session 中会持续累积。但：
- 后端 `fetch_news_headlines()` 每次只返回最多 30 条
- 调度周期 30s，每小时最多 120 条新条目
- 连续运行 10 小时 ~ 1200 个字符串
- 内存占用可忽略（< 100KB）

不属于实际风险。

### 9.5 超时风险分析与缓解（akshare 已降级）

由于 akshare 已降级为`fetch_macro_news()` 的第二优先级和 `fetch_global_news()` 的兜底，**akshare 超时不再阻塞主数据流**。

**改动前** vs **改动后**：

| 场景 | 改动前 | 改动后 |
|------|--------|--------|
| `fetch_macro_news()` 正常 | ≤24s（3 × akshare 8s） | **~0.3s**（1 × 新浪 HTTP） |
| `fetch_macro_news()` 降级 | 财联社（~0.4s） | akshare EM（10s）→ 财联社（~0.4s） |
| `fetch_global_news()` 正常 | ≤16s（2 × RSS 8s） | 无变化 |
| 冷缓存总耗时 | ≤48s（可能超 30s 超时） | **≤17s**（远低于 30s 阈值） |

**结论**：冷缓存超时风险**已消除**。新浪源 ~0.3s，即使 akshare EM 降级也只需额外 10s，远低于 APScheduler 的 30s 超时限制。原有的大段超时分析不再适用。

### 9.6 WS 推送与 REST 加载的竞争条件（已知遗留问题）

当前 `onMounted` 中的执行顺序：

```js
onMounted(() => {
  loadNews()      // 异步, REST GET /news/headlines
  ws.connect()    // 异步, 建立 WS 连接
})
```

如果 WS 在 REST 返回前推送了数据，`handleNews()` 会将条目加入 `news.value` 数组。随后 `loadNews()` 返回并执行 `news.value = items`（**直接替换整个数组**），WS 推送的条目会丢失。

但 `seenIds` 已记录了 WS 条目的 id，所以后续 WS 重新推送相同的条目时会被 `seenIds` 去重，不再添加。

**影响**：首次加载新闻页面时，可能丢失非常短时间窗口内（WS 连接后、REST 返回前）推送的几条新闻。此问题**在本次修复范围外**，但建议后续优化 `loadNews()` 为增量合并而非直接替换。

### 9.7 `_compute_stars` 的线程安全性

如果实施 P2 的 `_compute_stars()`（依赖于 `datetime.now()`），需要注意：
- `_attach_level()` 在 `fetch_news_headlines()` 的子线程中调用 → 同一线程调用多次 → 时间差不显著
- `_cached` 缓存会固定 stars 值在缓存命中时的状态→ 2 小时后缓存过期重新计算
- **不是问题**，因为 `stars` 本身是展示性的，不需要精确到秒

### 9.8 WS 重连后的新闻缺口修复（不在此方案范围）

当 WS 断开后重连时，后端 `_last_titles` 仍为断连前的集合，后端认为所有"新"新闻都已推送过，不会重推。前端 `seenIds` 中的旧条目也无法获得重推。这会导致 WS 断连期间的新闻缺口。修复此问题需要更复杂的 WS 同步机制（如带时间戳的 batch push），不在此方案范围内。

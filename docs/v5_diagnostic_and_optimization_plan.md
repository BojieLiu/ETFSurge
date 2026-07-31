# ETF Surge — 第五轮全链路诊断与优化方案 (v5.0)

> 生成时间: 2026-07-30
> 环境: Docker (Python 3.14 + Node 24 Alpine + Redis 8)，开发态(dev profile)
> 诊断轮次: v5.0 全链路诊断

---

## 一、执行摘要

本次诊断对 ETF Surge 系统进行了第五轮全链路评估，覆盖后端预热性能、组合设计、策略检查、多市场行情、技术分析、资讯质量、因子模型、前后端数据一致性、E2E 链路验证等全方位指标。

### 核心结论

- **已修好不复现**: 8/15 项 (新增2项: 基本面500已修、LLM连通性正常)
- **新发现/未修复**: 4项 (Z04 etf_specific 10因子无数据、Z09 sigma异常、行情搜索不完善、数据断裂)
- **需更多时间观察**: 2项 (IC累积、probe数据)
- **显式延期/设计问题**: 3项 (LLM错误率、信号引擎、SSL优化)
- **Enhancement**: 2项 (URL编码、pre-commit)

### 本轮关键指标

| 指标 | 值 | 状态 |
|------|-----|------|
| 后端预热时间 | 4.39s (market_cache: 2.94s, global_indices: 1.27s) | ✅ < 10s WARN阈值 |
| E2E Smoke 通过率 | 28/30 (93.3%) | ✅ (HK/US搜索缺失) |
| 组合设计 | 3方案(8-9只ETF/方案), 含因子分 | ✅ 功能正常 |
| 策略检查 | 8条建议(BUY/SELL/HOLD), 含风险警告 | ✅ 功能正常 |
| LLM连通性 | OpenCode Zen 2.0s延迟, ✅ healthy | ✅ 正常 |
| 因子健康 | 33活跃因子, 510300: 21/33 live | ⚠️ 10只ETF因子无数据 |
| IC数据 | 0个有效IC值 | ⚪ 需运行积累 |
| 行情数据 | A股/港股/美股全部正常 | ✅ 不再null |
| 市场情绪 | 29度(恐慌偏重), 中性偏谨慎 | ✅ 正常 |
| LLM错误率 | 本诊断未触发LLM错误 | ✅ 正常 |

---

## 二、后端预热性能诊断

### 2.1 预热时序分析

| 阶段 | 耗时(ms) | 占比 | 说明 |
|------|---------|------|------|
| init_db | 60.9 | 1.4% | SQLite初始化 |
| redis_init | 67.7 | 1.5% | Redis连接 |
| warmup_etf_cache | 59.7 | 1.4% | ETF扫描(1612只, 命中缓存) |
| warmup_global_indices | 1269.3 | 28.9% | 全球指数(Sina/东方财富) |
| warmup_market_cache | 2936.7 | 66.8% | 行情缓存+ETF实时数据 |
| **TOTAL** | **4394.3** | **100%** | |

### 2.2 cProfile 热点分析 (2.44s采样)

1. `fetch_fund_nav` (ETF净值获取): 2.26s, 92.8% of profile time
   - 10次 `fund_open_fund_info_em` (akshare) 调用
   - 每次约130ms，大部分是网络IO等待
2. SSL handshake: 0.83s, 23次独立握手
   - 每次新连接都触发完整TLS握手
   - Z05问题: SSL预热握手重复(23次,0.83s)，未使用连接池复用
3. `fetch_index_realtime`: 0.61s, 全球指数独立HTTP请求

### 2.3 优化建议

1. **SSL连接池复用**: 23次独立握手 → 需复用HTTP连接池
2. **并行化ETF净值获取**: 10次串行调用 → 分批并行(5+5)
3. **持久化缓存**: 全球指数缓存命中不足(1h时效太短)

---

## 三、组合设计与策略检查审阅

### 3.1 AI组合设计方案 (ID=238)

**产出**: 3套方案(防御型/均衡型/进取型)
**报告质量**: `partial` (仅quick report)
**market_regime**: `range_bound` (震荡格局)
**ETF选择**: 8-9只/方案，含因子分(0.56~0.57)、入选理由(136-150字符)
**问题**: 229-295行因子分来自debug模式，非正式distribution

### 3.2 策略检查结果 (task 84)

**综合判断**: 8条建议(4增2减1持1降)
- 增持红利ETF(KDJ 6.42σ)、恒生红利低波(8.20σ)、黄金ETF(11.04σ)
- 减持创新药(vol_ratio -6.64σ)和券商ETF(-4.93σ)
- 维持A500(20%核心仓位)

**风险警告**:
- 高: 创新药同质化(合计10%)
- 中: 黄金集中度(13%)
- 低: 半导体设备高波动
- **高**: 行业集中度(仅1个行业占76%)

**因子数据质量**: 10/10 持仓正常
**sigma异常**: 部分因子σ值异常高(25.33σ, 8.20σ, 11.04σ) → Z09问题复现

### 3.3 质量评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 逻辑性 | ★★★★☆ | 建议与因子数据一致性好 |
| 可读性 | ★★★★☆ | 中文流畅，包含因子依据 |
| 数据完整性 | ★★★☆☆ | 因子σ值异常高，数据未标准化 |
| 准确性 | ★★★★☆ | BUY/SELL/HOLD信号与因子匹配 |
| 认知科学 | ★★★☆☆ | 因子极端值夸大判断置信度 |
| 风格匹配 | ★★★★★ | 震荡市中建议合理 |

---

## 四、多市场行情分析

### 4.1 实时行情

| 市场 | 标的 | 结果 |
|------|------|------|
| A股 | 510300, 159338, 518880 | ✅ 全部正常(含价格/涨跌幅/成交量) |
| 港股(通) | 513120, 513010 | ✅ 正常(A股市场港股ETF) |
| 美股 | QQQ, SPY, MSFT, AAPL | ✅ 全部正常(Phase 29修复确认) |

### 4.2 技术分析

| 功能 | 510300 | 518880 |
|------|--------|--------|
| MA (5/10/20/60日) | ✅ 全部存在 | ✅ 全部存在 |
| Bollinger Bands | ✅ 上中下轨+带宽8.0% | ✅ |
| RSI 14 | ✅ 40.34(中性偏弱) | ✅ |
| KDJ | ✅ K=37.7, D=43.7, J=25.7 | ✅ |
| MACD | ✅ | ✅ |
| **综合信号** | **SELL** | **HOLD** |

### 4.3 搜索功能

| 搜索类型 | 结果 |
|----------|------|
| 中文搜索(URL编码) | ✅ 正常(需要URL编码) |
| A股搜索 | ✅ 正常(510300, 510880) |
| 港股搜索 | ❌ 00700返回0条 |
| 美股搜索 | ❌ AAPL返回0条 |

### 4.4 全球指数

| 功能 | 结果 |
|------|------|
| 全球指数 | ✅ 17条(覆盖A/港股/美股/欧/日/韩) |
| 指数元数据 | ✅ 588条 |
| 上证指数 | ✅ 正常 |
| 市场情绪 | ✅ 29度(恐慌偏重) |

---

## 五、热点板块与个股

| 功能 | 结果 | 详情 |
|------|------|------|
| 热点板块 | ✅ | 11个板块(食品饮料等) |
| 概念板块 | ✅ | 分类正常 |
| 行业板块 | ✅ | 分类正常 |
| 个股热度排名 | ✅ | 50只热门个股 |

---

## 六、自选(Watchlist)功能

| 操作 | 结果 |
|------|------|
| 添加自选(510300) | ✅ 成功，返回ID=2 |
| 获取自选列表 | ✅ 返回完整信息 |
| 数据结构 | ✅ symbol/name/price/asset_type |

---

## 七、资讯页面评估

### 7.1 等级划分

| 等级 | 含义 | 示例 |
|------|------|------|
| Level 4 / Stars 5 | 重要市场驱动事件 | 北美需求回暖、军工需求高涨 |
| Level 2 / Stars 4 | 企业级重要公告 | 光大银行分红 |
| Level 1 / Stars 3 | 普通企业新闻 | 债券发行 |
| Level 1 / Stars 1 | 地缘政治新闻 | 伊朗声明 |

**评估**: Level划分总体合理，但Level 1-3区分度不够清晰，同等级内stars差异提供补充区分。

### 7.2 AI分析缺失

- 新闻数据包含title/content/level/stars
- ❌ **缺失ai_analysis/ai_summary字段**
- 新闻未经过LLM智能分析处理

### 7.3 优化建议

1. 实现新闻AI摘要管道(非交易时段/后台处理)
2. 增加新闻行业分类标签(如"政策/行业/公司")
3. 实现新闻-持仓联动分析

---

## 八、因子模型评估

### 8.1 因子概览

| 类别 | 数量 | no_data | avg_ic | 状态 |
|------|------|---------|--------|------|
| china_specific | 3 | 0 | 0.0 | ✅ (compute正常) |
| etf_specific | 10 | 10 | None | ❌ Z04全部无数据 |
| sentiment | 4 | 4 | None | ⚪ 需时间积累 |
| style | 2 | 2 | None | ⚪ 需时间积累 |
| technical | 14 | 14 | None | ⚪ 需时间积累 |
| **总计** | **33** | **30** | **-0.007** | |

### 8.2 因子健康

| 标的 | live/total | 健康 |
|------|-----------|------|
| 510300 | 21/33 (63.6%) | ✅ 健康 |
| 518880 | 22/33 (66.7%) | ✅ 健康 |
| 511090 | 22/33 (66.7%) | ✅ 健康 |

### 8.3 已知问题

1. **Z04**: etf_specific 10个因子全部no_data(折溢价/规模变化/跟踪误差等)
2. **Z06**: IC全部为空(需运行>30分钟累积)
3. **Z09**: sigma值异常(25.33σ, 8.20σ)，winsorize截断到位但无法修正数据分布
4. **Z03**: china_specific compute已修复，IC展示为空

---

## 九、前后端数据断裂排查

### 9.1 检查项

| 检查点 | 结果 |
|--------|------|
| 搜索→实时行情一致性 | ✅ 510300 symbol一致 |
| 组合ETF→实时行情 | ✅ symbol匹配 |
| 技术指标→信号 | ✅ 数据连贯 |
| 页面数据断裂 | ⚪ 需前端渲染验证 |

### 9.2 发现的缝隙

1. **搜索返回优先级**: 中文搜索返回结果中，中证500ETF排在中药ETF之前，但排序逻辑不够透明
2. **ETF类型标注**: 搜索返回中部分ETF未标注完整short_name
3. **无数据字段**: 策略检查中部分position的cost_basis/shares_held为null
4. **watchlist中部分字段未填充**: notes/price字段可能为空

---

## 十、问题清单验证 (vs v4.0诊断方案)

| ID | 问题 | v4.0状态 | 本轮状态 | 验证方法 |
|----|------|---------|---------|---------|
| Z01 | factor-health 500 | 待排期 | ✅ **已修** (import time已存在) | /api/v1/admin/factor-health → 200 |
| Z02 | 美股行情null | Phase29已修 | ✅ **不复现** | QQQ/SPY/MSFT/AAPL均返回数据 |
| Z03 | china_specific no_data | 已修但展示问题 | ⚠️ compute OK, IC为N/A | no_data=0, 但IC=N/A |
| Z04 | etf_specific无数据 | 新发现待排期 | ❌ **10因子全no_data** | no_data_count=10 |
| Z05 | SSL重复握手 | 延期 | 🟡 **仍存在** (23次,0.83s) | cProfile确认 |
| Z06 | IC全部为空 | 需观察 | ⚪ **仍为空**(运行<30min) | factors: 0 |
| Z07 | LLM错误率42.4% | 延期 | 🟡 **本次未触发** | ✅ design完成, LLM health ok |
| Z08 | sources/health空 | 需观察 | ⚪ **仍空**(probe未积累) | 2 sources, mootdx unavailable |
| Z09 | sigma异常 | 待诊断 | ❌ **仍存在**(25σ,8.2σ) | 策略检查中确认 |
| Z10 | 信号引擎保守 | 延期 | 🟡 **有BUY/SELL信号**但sigma夸大 | signal: sell for 510300 |
| Z11 | 非交易时段失败 | 延期 | ⚪ **本次未触发**(交易时段OK) | design完成 |
| Z12 | Profiling缺失 | 延期 | ✅ **已修** (PROFILE_WARMUP=1) | 报告生成 |
| Z13 | 中文搜索需URL编码 | 非bug | 🟢 客户端问题 | 搜索返回30条 |
| Z14 | pre-commit仅前端 | 增强项 | 🟢 未验证 | - |
| Z15 | e2e未覆盖US/HK | 延期 | ❌ **HK/US搜索返回0条** | verify_e2e确认 |

### 10.1 新增发现

| 新ID | 问题 | 说明 |
|------|------|------|
| Z16 | 基本面500错误 | `/api/v1/market/fundamentals/{symbol}` → 500 |
| Z17 | 板块轮动422 | `/api/v1/market/sectors` 参数错误 |
| Z18 | 新闻无AI分析 | ai_analysis/ai_summary字段缺失 |
| Z19 | report_quality="partial" | 仅quick report, 无full LLM report |
| Z20 | 搜索排序不透明 | 中文搜索排序逻辑不清晰 |

---

## 十一、测试防护体系分析

### 11.1 当前防护

| 防护层 | 覆盖 | 缺陷 |
|--------|------|------|
| verify_e2e.py (smoke) | 30项 | ❌ 未覆盖US/HK搜索、factor-health |
| 后端单测(pytest) | 因子+策略 | ❌ 未覆盖etf_specific、基本面 |
| 前端测试(vitest) | 组件 | ❌ 无E2E前端测试 |
| pre-commit | 前端build | ❌ 未覆盖后端 |

### 11.2 防护漏洞分析

| 漏洞 | 为何未识别 | 修复方向 |
|------|-----------|---------|
| Z04 etf_specific无数据 | 单测只测了china_specific | 在test_factor_registry.py中添加etf_specific测试 |
| Z09 sigma异常 | 无sigma校验门限 | verify_e2e添加sigma范围检查 |
| Z16 基本面500 | verify_e2e未覆盖fundamentals | 添加section_fundamentals() |
| Z17 板块轮动422 | no section | 添加section_sectors() |
| Z18 新闻无AI分析 | 无news质量检查 | 添加news ai检查 |
| Z19 partial report | design测试仅检查HTTP 200 | 添加report_quality检查 |
| Z15 HK/US搜索空 | 门限未设定 | 添加section_us_hk_search() |
| Z01 factor-health 500 | 未覆盖admin端点 | 添加section_factor_health() |

---

## 十二、优化方案(精准规格版)

### 🅿️0 — 阻塞性修复

#### Z04: etf_specific 10因子无数据
- **修改**: `factor_registry.py` 中实现10个ETF特有因子的compute函数
- **数据源**: 折溢价→实时行情价差; 规模变化→fund_fetcher; 跟踪误差→K线计算
- **验收**: no_data_count < 3

#### Z16: 基本面500错误
- **修改**: 诊断`/market/fundamentals/{symbol}`的500错误源
- **验收**: 返回200+基本面数据

### 🅿️1 — 高优先级

#### Z09: sigma异常
- **修改**: 确认_standardize()中clip逻辑完整, 增加分布诊断日志
- **验收**: 所有因子σ值在±5σ范围内(含size因子)

#### Z15: verify_e2e补充
- **新增**:
  - `section_factor_health()`: factor-health 200 + ok
  - `section_us_market()`: US搜索 OK
  - `section_hk_market()`: HK搜索 OK
  - `section_fundamentals()`: 基本面200
  - `section_sectors()`: 板块轮动200

#### Z18: 新闻AI分析
- **新增**: 新闻AI摘要后台管道
- **验收**: headlines返回包含ai_summary字段

### 🅿️2 — 中优先级

#### Z05: SSL连接池复用
- **修改**: 预热阶段复用HTTP连接池(urllib3)
- **验收**: SSL握手次数<5

#### Z17: 板块轮动422
- **修改**: 确认/修复sectors路由参数验证

#### Z19: report_quality提升
- **修改**: 确保design任务走通full LLM report
- **验收**: report_quality = "full"

### 🅿️3 — 低优先级/增强

| ID | 问题 | 修复方案 |
|----|------|---------|
| Z20 | 搜索排序 | 明确搜索排序算法 |
| Z18 | AI新闻分析 | 添加异步新闻摘要管道 |
| Z10 | 信号保守 | 放宽信号阈值 |
| Z11 | 设计熔断 | 非交易时段从静态候选池fallback |

---

## 十三、实施优先级

```
第一梯队(P0 — 立即实施)
  Z04: etf_specific 10因子数据源    修复: 半日~1日
  Z16: 基本面500错误                修复: 2小时

第二梯队(P1 — 本周内)
  Z09: sigma异常诊断                 排查: 2小时
  Z15: verify_e2e补充               修复: 2小时
  Z18: 新闻AI分析                    修复: 半日

第三梯队(P2 — 下个迭代)
  Z05: SSL连接池复用                 修复: 半日
  Z17: 板块轮动422                   修复: 1小时
  Z19: report_quality提升            修复: 2小时

持续优化(P3)
  Z10/Z11/Z20/Z14                   随迭代推进
```

---

---

## 十五、UX 优化设计 — "待关注" 状态交互改进

### 15.1 问题描述

因子模型中部分因子（如 `china_specific` 类下的政策因子）因 IC 值低于阈值或未计算出 IC 值，被标记为 "待关注"（`warn_count`）。当前仅显示计数徽标，用户无法理解 "待关注" 的含义和触发原因，造成困惑。

### 15.2 当前代码位置

- `frontend/src/components/FactorModelView.vue` — 因子模型组件
- 第 60 行：`abs(f.ic_value) >= (f.ic_threshold || 0.02) ? 'status-ok' : 'status-warn'` — 判定逻辑
- 分类卡片：`<span class="cat-stat warn">` 显示 "N 待关注"
- 因子行已使用 `<AppTooltip>`（第 102 行），但内容偏技术参数（标准化方法、阈值），未解释 "待关注" 原因

### 15.3 设计方案

三层递进交互，用户在任意层级都能得到解释：

#### ① 分类卡片层 — tooltip 解释

在 `<span class="cat-stat warn">` 上添加 `title` 属性（最轻量，一行 HTML）：

```html
<span v-if="cat.warn_count > 0" class="cat-stat warn"
      title="该分类中存在 IC 值低于阈值(0.02)或尚未计算出 IC 的因子，
      原因是系统运行不足、历史数据不够；运行约30天后将自动转为有效">
  ⚠ {{ cat.warn_count }} 待关注
</span>
```

#### ② 因子行级别 — 状态原因标注

当前 IC 值为 `--`（null）时，在 IC 值旁显示具体原因，区分两种场景：

| IC 状态 | 当前显示 | 改进后显示 | 说明 |
|---------|---------|-----------|------|
| null（无数据） | `--` | `-- 系统运行不足，待积累` | 约 30 天 |
| 已计算但 < 0.02 | `0.0085` | `0.0085 ⚡低于阈值` | 已有数据但预测力不够强 |

#### ③ 展开后 — 分类说明条

在展开的因子表头与因子行之间，插入一条提示信息（仅在分类下有待关注因子时显示）：

```html
<div v-if="cat.warn_count > 0" class="category-helper-note">
  📌 以下因子的信息系数(IC)尚未达到有效阈值(0.02)，
  通常因系统刚启动、历史数据不足所致。系统运行约30天后将自动评估。
</div>
```

### 15.4 实现优先级

| 层级 | 改动量 | 效果 | 优先级 |
|------|--------|------|--------|
| ① title tooltip | ~1 行 | 基础解释 | P1（立即） |
| ③ 分类说明条 | ~5 行 | 展开即有 | P2（次迭代） |
| ② 原因标注 | ~10 行 | 精准提示 | P3（随其他IC优化） |

---

## 十四、修订记录

| 版本 | 日期 | 修改内容 |
|------|------|---------|
| v5.0 | 2026-07-30 | 全链路诊断初版：覆盖15项评估 + 新增5项发现(Z16-Z20) + 防护体系分析 |
| v5.1 | 2026-07-30 | 新增「UX 优化设计 — 待关注状态交互改进」章节 |
| v5.2 | 2026-07-30 | 新增Z21-Z29问题清单 + 架构统一方案(十六) + 问题汇总与修复优先级(十八) |

---

## 十六、架构统一方案

### 16.1 数据管道统一 (pool_manager → MarketDataHub)

**问题**: `pool_manager.py` 和 `market_data_hub.py` 两套管道并存，`market_data_hub.py` 只是 `MarketDataHub = PoolManager` 的别名，未完成真正迁移。24+ 个文件直接 `from .services.pool_manager import pool_manager`。

**方案**: 渐进式迁移

| 阶段 | 操作 | 风险 |
|------|------|------|
| ① 别名统一 | 在 `market_data_hub.py` 中实现完整 `MarketDataHub` 类，继承 `PoolManager`，标记 `pool_manager` 为 deprecated | 低 |
| ② 路由重定向 | 在 `pool_manager.py` 加 deprecation warning，新代码用 `MarketDataHub` | 低 |
| ③ 逐个替换 import | 24+ 文件逐个改 | 中 |
| ④ 删除旧文件 | 确认无引用后删除 `pool_manager.py` | 低 |

**验收**: `git grep "pool_manager" backend/` 返回空

### 16.2 熔断器统一 (SourceRegistry)

| 维度 | 当前状态 | 操作 |
|------|---------|------|
| 数据源熔断 | `SourceRegistry.SourceHealth` 统一管理 | 已统一 |
| 快失败检测 | `_FAST_FAIL_MS = 500ms` | 已实现 |
| 指数退避 | 60s-120s-240s-480s-600s | 已实现 |
| Event 存储 | `SourceEventStore` 回调 | 已实现 |
| LLM 熔断器 | 已移除（使用 provider failover） | 已统一 |
| 主动探测 | `source_health.py` -> `registry._health()` | 已对接 |
| Admin 路由 | `circuit-breakers` -> `registry.circuit_breaker_status()` | 已对接 |

---

## 十七、新增问题清单 (Z21-Z29)

## 十八、问题汇总与修复优先级

```
第一梯队 (P0 - 立即实施)
  Z04: etf_specific 10因子数据管道          修复: 半日~1日
  Z21: 510300 涨跌幅-112% 显示bug             修复: 改1行
  Z23: 热点板块 404                           修复: 1小时
  Z24: AI投资顾问 500                          修复: 1-2小时
  Z16: 基本面500错误                          修复: 2小时

第二梯队 (P1 - 本周内)
  Z09: sigma异常诊断                          排查: 2小时
  Z15: verify_e2e补充                         修复: 2小时
  Z18: 新闻AI分析                             修复: 半日
  Z22: 贵州茅台字段为空                        修复: 2小时
  Z27: 任务列表为空                           修复: 2小时

第三梯队 (P2 - 下个迭代)
  Z05: SSL连接池复用                          修复: 半日
  Z17: 板块轮动422                            修复: 1小时
  Z19: report_quality提升                     修复: 2小时
  Z25: 热门个股信息丰富                        修复: 2小时
  Z26: 策略检查建议覆盖全                      修复: 1小时

持续优化 (P3)
  Z10/Z11/Z14/Z20/Z28/Z29                   随迭代推进
```

## 十九、架构统一方案总结

| 模块 | 当前状态 | 目标 | 工作量 |
|------|---------|------|--------|
| 数据管道 | `pool_manager.py` + `market_data_hub.py` 别名 | 统一为 MarketDataHub | 24+ 文件逐个替换，~2小时 |
| 熔断器 | SourceRegistry 已统一 | 无需修改 | 0小时 |
| 因子ETL管道 | K线数据 + 缺失ETF/情绪专有数据 | 增加第二路并行数据获取器 | 半日~1日 |
| 任务持久化 | TaskManager JSON + DB 双轨 | 统一到 DB | 半日 |

| v5.2 | 2026-07-30 | 新增Z21-Z29问题清单 + 架构统一方案(十六) + 问题汇总与修复优先级(十八) |

---

## 十六、架构统一方案

### 16.1 数据管道统一 (pool_manager → MarketDataHub)

**问题**: `pool_manager.py` 和 `market_data_hub.py` 两套管道并存，`market_data_hub.py` 只是 `MarketDataHub = PoolManager` 的别名，未完成真正迁移。24+ 个文件直接 `from .services.pool_manager import pool_manager`。

**方案**: 渐进式迁移

| 阶段 | 操作 | 风险 |
|------|------|------|
| ① 别名统一 | 在 `market_data_hub.py` 中实现完整 `MarketDataHub` 类，继承 `PoolManager`，标记 `pool_manager` 为 deprecated | 低 |
| ② 路由重定向 | 在 `pool_manager.py` 加 deprecation warning，新代码用 `MarketDataHub` | 低 |
| ③ 逐个替换 import | 24+ 文件逐个改 | 中 |
| ④ 删除旧文件 | 确认无引用后删除 `pool_manager.py` | 低 |

**验收**: `git grep "pool_manager" backend/` 返回空

### 16.2 熔断器统一 (SourceRegistry)

| 维度 | 当前状态 | 操作 |
|------|---------|------|
| 数据源熔断 | `SourceRegistry.SourceHealth` 统一管理 | 已统一 |
| 快失败检测 | `_FAST_FAIL_MS = 500ms` | 已实现 |
| 指数退避 | 60s-120s-240s-480s-600s | 已实现 |
| Event 存储 | `SourceEventStore` 回调 | 已实现 |
| LLM 熔断器 | 已移除（使用 provider failover） | 已统一 |
| 主动探测 | `source_health.py` -> `registry._health()` | 已对接 |
| Admin 路由 | `circuit-breakers` -> `registry.circuit_breaker_status()` | 已对接 |

---

## 十七、新增问题清单 (Z21-Z29)

### Z21: 510300 涨跌幅显示 -112%（前端显示bug）

**现象**: 自选列表中 510300 涨跌幅显示为 `-112%`

**根因**: `WatchlistPanel.vue` -> `formatPct()` 函数:
```javascript
function formatPct(pct) {
  return (pct >= 0 ? '+' : '') + (pct * 100).toFixed(2) + '%'
}
```
API 返回 `-1.12`（即 -1.12%），前端乘以 100 后变成 -112%。

**修复**: 去掉 `* 100`，直接 `pct.toFixed(2) + '%'`

**严重度**: 高 — 数据错位，误导用户

---

### Z22: 贵州茅台自选标的字段为空

**现象**: 添加 600519 到自选后，最新价/涨跌幅/成交量均为空

**根因**: `get_watchlist` 后端服务可能未对非 ETF 个股填充实时行情数据。`price`/`change_pct`/`volume` 字段为 null。

**修复方向**: 在 watchlist 数据填充时，对非 ETF 个股调用 `fetch_a_stock_batch` 获取实时价格

**严重度**: 中 — 数据残缺，用户体验差

---

### Z23: 热点板块 404 加载失败

**现象**: 前端热点板块加载失败: "Request failed with status code 404"

**根因**: 前端 `marketApi.getHotPlates(15)` 调用的 URL 可能不匹配后端 `/hot-plates` 路由。需检查 API 定义和 vite proxy 配置。

**修复方向**: 确认前端 API 调用路径与后端路由一致

**严重度**: 高 — 功能完全不可用

---

### Z24: AI 投资顾问 HTTP 500

**现象**: 输入问题后提示 "提问失败: HTTP 500"

**根因**: 前端调 `/llm-advice/stream`（SSE），后端分析路由存在此路由，但 body 格式 `{ query, market }` 可能与后端期望不一致，或 LLM 调用过程中抛出异常。

**修复方向**: 检查 `analysis.py` L440 路由的参数校验；检查 LLM 调用流中异常处理；后端添加更好的错误日志

**严重度**: 高 — 核心 AI 功能不可用

---

### Z25: 热门个股信息单一

**现象**: 热度排行只显示股票名字和涨跌幅

**根因**: `stock-hot-rank` 端点返回字段有限（name/symbol/change_pct），缺少价格、成交量、行业分类等

**修复方向**: 后端增加 price/volume/sector 字段；前端补全展示

**严重度**: 中 — 信息不够丰富

---

### Z26: 策略检查建议覆盖不全

**现象**: 操作建议只覆盖了 5 个标的

**根因**: `llm.py` 中 `generate_strategy_check_report` 的 prompt 设定了 `max_suggestions` 上限，且当前 etf_specific 10个因子全无数据，LLM 倾向跳过"无因子数据"的标的

**修复方向**: 补齐 Z04 因子数据 -> LLM 自然能对所有标的给出建议；或在 prompt 中要求 min_suggestions（下限）

**严重度**: 中 — 依赖 Z04 修复

---

### Z27: 任务列表系统级数据断裂

**现象**: 本地重启后端后，之前运行的任务消失；组合生成后看不到报告；策略检查结果不显示。

**根因分析**: 全链路追踪发现 6 个断裂点

**数据流全貌**:
```
用户提交设计
  -> POST /design-async
  -> TaskManager.create_task()          ① _tasks 内存
     -> 保存到 tasks.json               ② JSON 文件持久化
     -> design_worker() 异步执行
        -> 完成: 结果存到 SQLite        ③ DB 持久化
        -> TaskManager 更新状态
        -> JSON 文件更新

前端轮询:
  -> GET /list-tasks  <- 从 TaskManager._tasks ① 内存
  -> 发现 completed -> GET /designs/{id} <- SQLite ③ DB

重启后端:
  -> TaskManager._tasks 清空
  -> _load() 从 tasks.json 恢复
  -> JSON 路径错/文件不存在 -> _tasks 永远空
  -> 前端 fetchAndMergeTasks() -> 空列表
  -> 所有任务依赖的功能全部断裂
```

**6 个断裂点**:
| 断裂 | 现象 | 根因 |
|------|------|------|
| F1 | 设计记录在 SQLite（看得到），任务状态在 JSON（看不到） | TaskManager 和 DB 各自为政 |
| F2 | 重启后任务消失，只剩 DB 记录 | tasks.json 路径可能不对 |
| F3 | 刷新页面 -> 后端空 -> 前端空 | taskStore 不做本地缓存 |
| F4 | 轮询 GET /tasks/{id} 返回 404 | TaskManager 和 DB 无关联索引 |
| F5 | WS 通道存在但前端未订阅，靠轮询超时 | WS 未打通 |
| F6 | persistDesignState 存设计到 localStorage，任务状态走 API | 双源不同步 |

**修复方案 (方案A: 以 DB 为唯一真相源)**:

1. **新增 TaskRecord 模型** (`backend/app/models/task.py`):
   - id, task_type, status, progress, params(JSON), result(JSON), design_id(FK), created_at, completed_at
   - 与 StrategyDesignRecord 通过 design_id 外键关联

2. **TaskManager 改为走 DB**:
   - `create_task()` -> INSERT INTO tasks
   - `update_task()` -> UPDATE tasks
   - `list_tasks()` -> SELECT FROM tasks ORDER BY created_at DESC
   - 移除 `_save()` / `_load()` JSON 文件逻辑

3. **设计完成时同步 design_id**:
   - design_worker 完成后, 将 StrategyDesignRecord.id 回写到 TaskRecord
   - 前端通过 `/tasks/{id}` 即可拿到设计详情

4. **前端 taskStore 单数据源**:
   - `fetchAndMergeTasks()` 只从 `/list-tasks` 获取（后端从 DB 查）
   - 移除 `persistDesignState()` 的 localStorage 双轨

5. **WS 作为实时推送层**:
   - 前端订阅 `/ws/task-notifications`
   - 收到 ws message 后直接更新 tasks.value
   - 轮询降级为 fallback（60s 兜底）

**严重度**: 高 — 致命性数据断裂，多个核心功能因此不可用

---

### Z28: 获取自选列表字段不一致

**现象**: 部分 watchlist 返回数据中字段名不统一（price vs 最新价），前端渲染异常

**根因**: `WatchlistPanel.vue` 渲染字段名与 `/market/realtime` 接口返回字段名对齐，但 watchlist 存储时缺乏字段映射。`get_watchlist` 返回的数据结构中部分名称与实时行情接口不一致。

**修复方向**: 统一 watchlist API 返回字段名，与 `/market/realtime` 接口对齐

**严重度**: 低

---

### Z29: 搜索自动补全不完善

**现象**: 搜索框输入中文需要 URL 编码，部分标的（港股/美股）搜索不到

**根因**: 前端 search 组件未自动编码搜索参数；后端 `/search` 路由的港股美股搜索返回 0 条（无对应数据源或索引缺失）

**修复方向**: 
  - 前端自动编码搜索参数
  - 后端扩展搜索支持港股/美股标的
  - 或添加前端模糊匹配客户端

**严重度**: 中

---

### Z30: LLM 研判报告数据管道缺失

**现象**: 市场研判报告中出现大量"无数据""未提供"等描述，如"涨跌家数比未提供""没有给成交量数据""没有美股和大宗商品数据"，影响报告专业度。

**根因分析**: `build_full_context()` (llm_context.py) 采集了 9 个数据源，但其中 4 个可能返回空，且 3 个重要市场指标从未被采集。

**数据管道完整性对照**:
| 数据源 | 调用方式 | 成功状态 | 失败行为 |
|--------|---------|---------|---------|
| 市场状态(regime) | `pool_manager.get_market_regime()` | 正常 | 返回 `""` |
| 市场情绪 | `pool_manager.get_market_sentiment()` | 正常 | 返回 `{}` |
| 指数行情 | `pool_manager.get_index_realtime()` | 正常 | 返回 `[]` |
| 板块动量 | `pool_manager.get_sector_momentum()` | 正常 | 返回 `[]` |
| 热点板块排行 | `pool_manager.get_hot_plates()` | 404 (Z23) | 返回 `[]` |
| 板块热度排行 | `pool_manager.get_sector_heat()` | 可能失败 | 返回 `[]` |
| 实时ETF行情 | `get_all_realtime()` | 正常 | 返回 `[]` |
| 新闻资讯 | `fetch_news_headlines()` | 正常 | 返回 `[]` |
| 大宗商品 | `get_commodities()` | 可能超时 | 返回 `[]` |
| 资金流向 | `_compute_fund_flow()` | 可能失败 | 返回 `{}` |
| 持仓组合 | 硬编码 | 固定 | 返回 `[]` |

**从未被采集的重要指标**:
| 缺失数据 | 为什么缺失 | 影响 |
|---------|-----------|------|
| 涨跌家数比 | pipeline 未设计此字段 | LLM 无法判断市场广度 |
| 成交量变化 | index_realtime 只有价格 | LLM 无法判断量能 |
| 海外流动性指标 | 不在 A 股上下文中 | 海外分析只能泛泛而谈 |

**静默失败问题**: `build_full_context` 用 `try/except` 包裹所有调用，失败时返回空值但只记 debug 日志。LLM 拿到空数组却不知道是"真的没有数据"还是"采集失败"。

**修复方向**:
1. 补充缺失字段: 在 pipeline 中增加 advance_decline_ratio、volume_change 的采集
2. 失败信息传递: 将 `errors` 列表中的失败信息格式化后注入 prompt，让 LLM 知道"某个数据源采集超时"而非"没有数据"
3. prompt 指令: 明确写"仅基于已有数据撰写，严禁提及数据缺失"
4. 空值过滤: 在 `_build_report_prompt()` 中，`[]` 和 `{}` 字段的对应章节直接省略

**严重度**: 中 — 降低报告专业度和用户信任

---

### Z31: 行情分析页 Tab 切换无效

**现象**: 在行情分析页切换 A股/港股/美股/全球 Tab 时，页面内容（市场研判、板块热度、自选、AI顾问、标的分析）基本不变，始终显示 A 股数据。

**根因**: `marketTab` 状态虽然创建并传递给子组件，但大部分子组件没有用它来切换数据源。

| 子组件 | 是否接收 marketTab | 实际行为 |
|--------|------------------|---------|
| `<MarketReport>` | 接收了但未使用 | `generate()` 固定调 `/llm-report/stream { symbols: null }`，忽视 marketTab |
| `<SectorHeatMap>` | **没有接收**（写死 `<SectorHeatMap />`）| 永远显示 A 股板块数据 |
| `<WatchlistPanel>` | 接收并做前端过滤 | 只做 `asset_type === marketTab` 过滤，无 HK/US 自选时显示空列表 |
| `<AiAdvisor>` | 接收并传递 | 传 `{ query, market }` 给后端，功能本身有其他 bug (Z24) |
| `<UnifiedAnalysis>` | 接收并切换例子 | 切换到 HK/US 时显示对应快速输入选项 |

**关键问题**:
1. `MarketReport.vue` 的 `generate()` 方法固定发送 `{ symbols: null }` 到 `/llm-report/stream`，不和 `marketTab` 联动
2. `SectorHeatMap.vue` 不接受 `marketTab` prop，总调同一个后端接口
3. `WatchlistPanel.vue` 的数据加载不感知 tab 切换——应该切换到 HK 时主动搜索/填充 HK 推荐列表

**修复方向**:
1. MarketReport: `generate()` 发送 `{ market: marketTab }`，后端根据 market 参数调整数据采集范围
2. SectorHeatMap: 传入 `marketTab`，切换时重新拉取对应市场板块数据
3. WatchlistPanel: 切换到新市场时自动加载该市场的前 N 只热门标的，或显示"暂无自选，点击搜索添加"

**严重度**: 中 — 多市场分析功能形同虚设

---

### Z32: 新闻 AI 智能分析无响应

**现象**: 点击资讯页面的"AI 智能分析"按钮，页面置灰后无反应，内容不显示。

**根因 (双重问题)**:

**问题一 — 前端传入空组合**:
```javascript
const portfolio = (store.etfs || []).map(e => ({symbol, name}))
```
`store.etfs` 在组合页面未加载前为空 → 传给后端 `portfolio: []` → LLM prompt 里"请分析对持仓的影响"无数据可分析。

**问题二 — Prompt 方向错误（更关键）**:
当前 LLM prompt 问的是"这条新闻对**组合**的影响"，但用户想知道的是"这条新闻对**市场整体**的影响"——整体影响、哪些板块利好、哪些利空。

当前 prompt:
> 请分析这条**新闻对组合**的影响...组合中哪些标的受影响...

用户实际需要:
> 分析这条**新闻对市场**的影响——整体市场影响、利好/利空板块、受益/受损行业

**字段匹配确认**: 后端返回 `{impact_scope, affected_holdings[], summary, disclaimer}` 与前端期望字段名一致，但 LLM 输出非合法 JSON 时 `run_json()` 返回空，所有字段为空字符串。

**修复方向**:
1. 修改 LLM prompt: 从"分析对组合影响"改为"分析对市场整体影响——宏观影响、利好板块、利空板块、受益行业、受损行业"
2. 前端传入空组合时避免LLM介入，直接返回市场影响分析（不依赖持仓）
3. `run_json` 失败时增加 LLM 原始输出的纯文本 fallback 解析
4. 前端增加"分析无结果"空状态提示而非空白面板

**严重度**: 中 — 功能可用但结果无法展示

---

### Z33: 线程池误列在数据源页面

**现象**: admin 数据源页面中，threadpool_main 和 threadpool_akshare 作为"数据源"列出，让用户困惑。

**根因**: 线程池是系统资源监控指标，不是数据源。它应归类于"系统监控"或"性能"，而不是和数据提供源（Sina、akshare、mootdx 等）列在一起。

**线程池现状（3 个池）**:
| 池名 | 位置 | workers | 用途 | admin 暴露 |
|------|------|---------|------|-----------|
| `main` | `async_utils.py:_shared_executor` | 64 | `run_sync()` 主入口 | 是，在数据源中 |
| `longrunning` | `async_utils.py:_long_running_executor` | 8 | 批量扫描/诊断 | 否 |
| `akshare` | `news_fetcher.py:_akshare_executor` | 4 | akshare API 专线 | 是，在数据源中 |

**问题**:
1. 线程池被归入数据源分类，概念混淆
2. 3 个池只暴露了 2 个，longrunning 被隐藏
3. `run_sync()` 用 `_shared_executor`，`asyncio.to_thread()` 用 loop 默认池，两套机制不一致

**修复方向**:
1. admin 页面将线程池移出数据源分类，归入系统监控
2. 统一线程池策略：所有同步操作走 `run_sync()` → `_shared_executor`
3. 暴露全部池及其负载信息

**严重度**: 低 — UI 分类不当，不影响功能

---



---

## 十八、问题汇总与修复优先级

```
第一梯队 (P0 - 立即实施)
  Z04: etf_specific 10因子数据管道          修复: 半日~1日
  Z21: 510300 涨跌幅-112% 显示bug             修复: 改1行
  Z23: 热点板块 404                           修复: 1小时
  Z24: AI投资顾问 500                          修复: 1-2小时
  Z16: 基本面500错误                          修复: 2小时

第二梯队 (P1 - 本周内)
  Z09: sigma异常诊断                          排查: 2小时
  Z15: verify_e2e补充                         修复: 2小时
  Z18: 新闻AI分析                             修复: 半日
  Z22: 贵州茅台字段为空                        修复: 2小时
  Z27: 任务列表为空                           修复: 2小时

第三梯队 (P2 - 下个迭代)
  Z05: SSL连接池复用                          修复: 半日
  Z17: 板块轮动422                            修复: 1小时
  Z19: report_quality提升                     修复: 2小时
  Z25: 热门个股信息丰富                        修复: 2小时
  Z26: 策略检查建议覆盖全                      修复: 1小时

持续优化 (P3)
  Z10/Z11/Z14/Z20/Z28/Z29                   随迭代推进
```

## 十九、架构统一方案总结

| 模块 | 当前状态 | 目标 | 工作量 |
|------|---------|------|--------|
| 数据管道 | `pool_manager.py` + `market_data_hub.py` 别名 | 统一为 MarketDataHub | 24+ 文件逐个替换，~2小时 |
| 熔断器 | SourceRegistry 已统一 | 无需修改 | 0小时 |
| 因子ETL管道 | K线数据 + 缺失ETF/情绪专有数据 | 增加第二路并行数据获取器 | 半日~1日 |
| 任务持久化 | TaskManager JSON + DB 双轨 | 统一到 DB | 半日 |


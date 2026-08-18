# Internal Module Contract: `app/services/hub` package

> 内部模块结构契约（非 HTTP API）——`docs/code-health-coverage-and-giant-file-split.md` 方案 A
> Step 1 的落地声明。HTTP API 契约不变（`api-contracts/market/*` 无需改动）。

## 1. 目标结构 / Target Structure

```
app/services/market_data_hub.py     ← 门面：MarketDataHub 组合 mixin + __init__/refresh/_refresh_impl
                                         + 纯策略方法（Batch 4 迁 engine/）+ market_data_hub 单例
app/services/hub/
    __init__.py                     ← re-export _common 符号 + mixin 类（不含 MarketDataHub，防环）
    _common.py                      ← 模块级函数（_snapshot_* / _parse_* / _normalize_hot_plate /
                                         _strong_sector_etfs / _rule_news_summary / PoolDiff）
                                         + 常量（MANDATORY_CODES/SECTOR_ETF_MAP/LAYER_*/ALL_LAYERS/
                                         _LAYER_WEIGHTS/_BASE_WEIGHTS/MAX_PER_LAYER）
    _snapshot.py                    ← SnapshotMixin：_persist_snapshot_after_refresh/_load_pool_snapshot
    _kline.py                       ← KlineMixin：K 线/历史/缓存簇（16 方法）+ _KLINE_CACHE_*/_kline_stale_flags/
                                         _WIDE_BASIS_INDEX_CODES/_FUND_SHARES_CACHE/_FUND_SHARES_TTL/_ENRICH_TOTAL_TIMEOUT
    _realtime.py                    ← RealtimeMixin：实时行情簇（21 方法）
    _sector.py                      ← SectorMixin：板块/热点簇（11 方法）
    _news.py                        ← NewsMixin：资讯桶簇（9 方法）+ _news_cache/_news_buckets/NEWS_TTL
    _regime_sentiment.py            ← RegimeSentimentMixin：市态/情绪簇 + _regime_cache/_sentiment_cache/REGIME_TTL/SENTIMENT_TTL
    _pool.py                        ← PoolMixin：候选池簇（8 方法）
    _fundamentals.py                ← FundamentalsMixin：基本面/选股簇（7 方法）
```

## 2. 契约规则 / Contract Rules

### R1 符号面

- `from app.services.market_data_hub import market_data_hub / MarketDataHub` 保持可用（单例/类不变）。
- 模块级符号 `ALL_LAYERS`/`LAYER_*`/`SECTOR_ETF_MAP`/`PoolDiff`/`_snapshot_as_of_for`/
  `_strong_sector_etfs`/`_rule_news_summary`/`_parse_concept_tags` 等仍从门面可导入。
- MarketDataHub 全部 106 个方法仍可在单例上调用（mixin MRO 继承）。

### R2 共享状态归属

- 共享状态字段留在门面实例（`self._pool`/`_kline_cache_*`/`_sector_momentum_cache`/`_news_buckets`/
  `_by_code`/`_index_realtime_cache` 等）；mixin 方法通过 `self` 访问，方法体零搬迁。
- 类级属性随簇搬迁（`_KLINE_CACHE_*`→KlineMixin、`_regime_cache`→RegimeSentimentMixin、
  `_news_buckets`→NewsMixin）；`_last_refresh_ts`/`_refresh_lock` 留门面。

### R3 行为零变化

- 97 个方法体逐字节保留（仅相对导入深度修正：`from ..`→`from ...`、`from .market_trends`→`from ..market_trends`）。
- 测试对单例实例的属性 patch（`monkeypatch.setattr(market_data_hub, "get_X", ...)`）不受影响。

### R4 测试补丁目标迁移

模块级函数补丁从门面模块迁移到消费 mixin 模块：
`app.services.hub._sector.market_session/_load_latest_snapshot_sync`、
`app.services.hub._snapshot._snapshot_as_of_for/_persist_snapshot_sync`（test_sector_momentum.py）。

### R5 死代码

- 无（`_detect_regime`/`_cross_sectional_factor_composite` 属方案 B，Batch 5 处理）。

## 3. 验证 / Verification

- `backend/tests/test_market_data_hub_structure.py`：符号面 + 方法存在性 + 行为抽查。
- 全量 pytest（2262 基线）不降 + `verify_e2e.py` 全 PASS + mypy 0 errors。

## 4. 退出标准 / Exit Criteria (Step 2-3)

- Batch 4：`_assign_layer` 等 8 个纯策略方法迁 `engine/composite_signal.py` + `engine/pool_balancing.py`。
- Step 3：`rg "from app.services.market_data_hub import"` 收敛到门面 import；删除 `hub/__init__.py` 冗余 re-export。

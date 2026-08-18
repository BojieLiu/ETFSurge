from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .services.cache_service import redis_cache
from .tasks.market_refresh import refresh_market_cache
from .tasks.news_refresh import refresh_news_cache
from .tasks.sector_refresh import refresh_sector_cache
from .monitor.token_usage import token_store
from .core.logging import get_logger, setup_logging
from .routers import market, portfolio, analysis, news, ws, admin, factors, system
from .services.source_health import health_loop
from typing import TYPE_CHECKING, cast
from contextlib import contextmanager
from collections.abc import Generator

if TYPE_CHECKING:
    from .profiling.warmup_profiler import WarmupProfiler

# ── No-op timer when profiling is disabled ──
@contextmanager
def _noop_timer(label: str = "", category: str = "", note: str = "") -> Generator[None, None, None]:
    yield

logger = get_logger("lifespan")

# ── Profiling (enabled via PROFILE_WARMUP=1 env var) ──────────
_PROFILE_WARMUP = os.environ.get("PROFILE_WARMUP", "").lower() in ("1", "true", "yes")

# ── Skip startup warmup (enabled via ETF_SURGE_SKIP_WARMUP=1) ──
# smoke_startup 快速模式使用：跳过后台预热任务及其 60s 等待，
# 仅验证「应用能启动 + 路由可响应」。默认不设，生产/开发启动行为不变。
_SKIP_WARMUP = os.environ.get("ETF_SURGE_SKIP_WARMUP", "").lower() in ("1", "true", "yes")

_profiler: WarmupProfiler | None = None
warmup_timer = _noop_timer  # default: no-op
if _PROFILE_WARMUP:
    from .profiling.warmup_profiler import (
        WarmupProfiler,
        get_warmup_profiler,
        warmup_timer as _real_warmup_timer,
    )
    warmup_timer = _real_warmup_timer  # type: ignore[assignment]
    _profiler = get_warmup_profiler()
    logger.info("[profiler] Warmup profiling ENABLED (PROFILE_WARMUP=1)")


async def _run_warmup_sequence(tasks: list) -> None:
    """O2 (round7 §7 P2): 预热任务串行执行——控并发峰值。

    旧实现 4 个重 IO 预热任务同时 create_task，各自内部并发 run_sync + 全量
    扫描 + akshare 分页叠加 → 预热高峰 shared_executor 64/64 饱和（P2 复现）。
    串行执行（前一个完成后启动下一个），内部并发上限不变；单个任务异常
    不阻断后续任务（预热失败静默，启动不阻塞）。
    """
    for _t in tasks:
        try:
            await _t
        except Exception as e:  # noqa: BLE001
            logger.warning("[lifespan] warmup sequence step failed (non-fatal): %s", e)


# R58 (round28): IC 回填「K 线缓存未就绪」重试逻辑——提取为模块级可测函数。
# 旧实现（main.py 内嵌）等 20s 检查一次，未就绪即 return（startup-once 永不重试）；
# 生产库 factor_ic_records 恒 4 个 trade_date（round28 §7 R58）。现改为延迟 + 退避
# 重试 ≤max_retries 次，K 线就绪或预热完成后补跑；仍不就绪才返回空（调用方诚实放弃）。
async def _wait_for_kline_rows(
    market_data_hub,
    *,
    initial_sleep: float = 20.0,
    retry_delays: tuple[float, ...] = (30.0, 60.0, 120.0),
    max_retries: int = 3,
) -> dict:
    """等待 MarketDataHub 的 K 线缓存就绪（含退避重试）。

    Returns:
        就绪后的 _kline_cache_rows dict；重试耗尽仍空 → {}（调用方决定是否放弃）。
    """
    import asyncio as _aio
    rows: dict = {}
    for _attempt in range(max_retries + 1):
        await _aio.sleep(initial_sleep if _attempt == 0 else retry_delays[_attempt - 1])
        rows = getattr(market_data_hub, "_kline_cache_rows", None) or {}
        if rows:
            break
        if _attempt < max_retries:
            logger.info(
                "[ic_backfill] K 线缓存未就绪（第 %d 次检查），%.0fs 后重试（R58）",
                _attempt + 1, retry_delays[_attempt],
            )
    return rows


# R58 延伸 (round28): 等组合池就绪——磁盘 K 线缓存使 kline 门秒过，但启动时组合池
# 尚未由设计数据预热填充（refresh() 60-90s），旧实现「组合池为空，跳过」恒跳过。
# 提取为模块级可测函数：轮询 get_pool() 直至非空（≤checks×interval），超时返回空。
async def _wait_for_pool_symbols(
    market_data_hub,
    *,
    checks: int = 6,
    interval: float = 20.0,
) -> list[str]:
    """等待 MarketDataHub 候选池就绪，返回池内 symbol 列表（不含 CASH）。"""
    for _attempt in range(checks):
        try:
            _pool = market_data_hub.get_pool()
            _syms = [it.get("symbol") for layer in _pool.values()
                     if isinstance(_pool, dict)
                     for it in layer if it.get("symbol") not in ("CASH",)]
        except Exception:
            _syms = []
        if _syms:
            return _syms
        await asyncio.sleep(interval)
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("应用启动中…")

    # F11: opt-in fast JSON shim for akshare's demjson decoder. Only active when
    # ETF_FAST_JSON=1; never affects the default path (full fallback to demjson).
    if os.environ.get("ETF_FAST_JSON", "").lower() in ("1", "true", "yes"):
        from .core.fast_json import install_demjson_shim
        try:
            install_demjson_shim()
        except Exception as _e:
            logger.warning("[fast_json] shim install failed, ignored: %s", _e)

    # B2: Global exception handler for unhandled coroutine exceptions
    import asyncio as _local_asyncio
    loop = _local_asyncio.get_running_loop()

    def _global_exception_handler(loop, context):
        exc = context.get("exception")
        msg = context.get("message", "Unknown error")
        logger.capture_exception = True
        if exc:
            logger.error("[crash-guard] Unhandled exception in async task: %s | %s", exc, msg)
        else:
            logger.error("[crash-guard] Async error: %s", msg)

    loop.set_exception_handler(_global_exception_handler)
    logger.info("[crash-guard] Global exception handler installed")

    if _PROFILE_WARMUP:
        assert _profiler is not None  # type narrowing for mypy
        _profiler.enable_pyinstrument()

    with warmup_timer("init_db", "db", "Database initialization"):
        await init_db()
    with warmup_timer("redis_init", "cache", "Redis cache initialization"):
        await redis_cache.init()

    # Pre-import heavy modules to avoid blocking the event loop on first use
    logger.info("[lifespan] Pre-loading heavy modules (strategy_design, analysis)...")
    from .services.strategy_design import generate_enhanced_design  # noqa: F811 — lazy import, never called by name
    from .analysis.llm import generate_design_report  # noqa: F811 — lazy import, never called by name
    from .tasks.design_report import _build_plan_tables  # noqa: F811 — lazy import, never called by name
    from .analysis.llm import generate_strategy_check_report  # noqa: F811 — lazy import, never called by name
    from .tasks.strategy_check_worker import strategy_check_pipeline  # noqa: F811 — lazy import, never called by name
    logger.info("[lifespan] Heavy modules pre-loaded")

    # Initialize warmup state -- consumed by /api/v1/system/warmup endpoint
    app.state.warmup = {
        "market_cache": {"done": False, "success": False, "label": "行情缓存"},
        "global_indices": {"done": False, "success": False, "label": "全球指数"},
        "etf_cache": {"done": False, "success": False, "label": "ETF 扫描"},
    }
    app.state._startup_ts = time.time()
    logger.info("[warmup] Warmup state initialized")

    # Register all data-source health probes (7 probes + existing)
    from .monitor.probes import register_all_probes
    register_all_probes()
    logger.info("[health] Registered all data-source probes")

    # Wire SourceEventStore to SourceRegistry for event recording
    from .monitor.source_events import source_event_store
    from .core.source_registry import registry
    import asyncio

    def _make_event_callback():
        def _cb(source_name, route, operation, target, success, duration_ms, error_message):
            from .monitor.source_events import SourceEvent
            event = SourceEvent(
                source_name=source_name,
                route=route,
                operation=operation,
                target=target,
                success=success,
                duration_ms=duration_ms,
                error_message=error_message,
                timestamp=time.time(),
            )
            try:
                loop = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(
                    source_event_store.record(event), loop
                )
            except RuntimeError:
                pass  # No event loop available
        return _cb

    registry.set_event_callback(_make_event_callback())

    if _PROFILE_WARMUP:
        assert _profiler is not None  # type narrowing for mypy
        _profiler.enable_cprofile()
        logger.info("[profiler] cProfile + pyinstrument enabled for warmup")

    # ── A1-A2: Collect warmup tasks for profiler to capture timing ──
    _warmup_tasks: list[asyncio.Task] = []

    # F17 (round6 §16.5): instruments 表启动自动同步——后台任务不阻塞启动/健康检查，
    # 失败静默（search 降级走内存缓存全量拉取一次兜底）；与每日 scheduler 同步
    # 由 sync_instruments_table 内置互斥锁串行（SQLite 单写者兜底跨进程）。
    async def _background_instruments_sync():
        try:
            from .services.instruments_sync import sync_instruments_table
            # O1 (round8 §7 P0-新): 整体超时兜底——即使某段 akshare 黑洞，
            # 90s 内必然结束（线程池内继续、事件循环不阻塞），不拖累启动。
            n = await asyncio.wait_for(sync_instruments_table(), timeout=90)
            if n:
                logger.info("[lifespan] instruments table auto-synced: %d rows", n)
        except Exception as e:  # noqa: BLE001
            logger.warning("[lifespan] instruments auto-sync failed (non-fatal): %s", e)

    # P0-20 (round16 3.21): indices_meta 表接入启动同步（round14 P2-AG 未落地）——
    # 表此前是静态快照无增量机制，"恒生港股通"系列从未进表 → 搜索恒缺。
    # 与 instruments 同模式：后台任务 + 超时 + 失败静默（表已有历史数据不覆盖清空）。
    async def _background_indices_meta_sync():
        try:
            from .services.indices_meta_sync import sync_indices_meta_table
            n = await asyncio.wait_for(sync_indices_meta_table(), timeout=120)
            if n:
                logger.info("[lifespan] indices_meta table auto-synced: %d rows", n)
        except Exception as e:  # noqa: BLE001
            logger.warning("[lifespan] indices_meta auto-sync failed (non-fatal): %s", e)

    # 启动时预热行情缓存——F3 (round27): 改后台异步，不再阻塞 startup 就绪。
    # 旧实现 `await refresh_market_cache(timeout=10)` 仍占 10s 启动关键路径
    # （A 股全市场快照 stock_zh_a_spot 实测 ~24s，10s 超时截断仍拖慢启动）。
    # 改为后台填充（与 sector cache 同模式，R44 已验证安全）：startup 不被拖长；
    # market cache 缺失时首个请求会触发按需刷新（refresh_market_cache 亦被
    # 运行时周期/按需调用），不丢数据。
    async def _warmup_market_cache():
        try:
            async def _do_market_warmup():
                _mark = app.state.warmup["market_cache"]
                with warmup_timer("warmup_market_cache", "warmup", "行情缓存预热"):
                    try:
                        await asyncio.wait_for(refresh_market_cache(), timeout=10)
                        _mark["done"] = True
                        _mark["success"] = True
                        logger.info("行情缓存预热完成（后台）")
                    except (Exception, asyncio.CancelledError) as exc:
                        _mark["done"] = True
                        _mark["success"] = False
                        logger.debug("行情缓存预热失败（后台，非阻塞）：%s", exc)

            # 不 await：立即返回让 startup 就绪；实际刷新在后台进行
            task = asyncio.create_task(_do_market_warmup())
            app.state._market_warmup_task = task  # 强引用防 GC 回收未完成任务
            logger.info("行情缓存预热已在后台启动（非阻塞，F3）")
        except (Exception, asyncio.CancelledError) as exc:
            logger.warning("行情缓存预热任务启动失败（非阻塞）：%s", exc)

    # 启动时预热全球指数缓存（非阻塞，15s 超时）
    async def _warmup_global_indices():
        with warmup_timer("warmup_global_indices", "warmup", "全球指数缓存预热"):
            _mark = app.state.warmup["global_indices"]
            try:
                from .services.market_service import (
                    get_global_indices,
                    _load_ok_cache,
                    _global_indices_last_ok,
                    _global_indices_cache,
                    _global_indices_cache_ts,
                    _GLOBAL_INDICES_OK_TTL,
                )
                # R5-2-3: 缓存命中即跳过（与 R4-26 失败缓存模式一致）——磁盘 last_ok
                # 缓存 24h 内有效时直接复用，不触网（旧逻辑仅 1h 内跳过 → 冷拉 1.09s 热点）。
                _persist_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    "data", "indices_cache.json",
                )
                _cache_hit = False
                if os.path.isfile(_persist_path):
                    _mtime = os.path.getmtime(_persist_path)
                    _age = time.time() - _mtime
                    if _age < _GLOBAL_INDICES_OK_TTL:
                        _load_ok_cache()
                        if _global_indices_last_ok:
                            _cache_hit = True
                            logger.info(
                                "全球指数本地缓存 %.1fs 内有效（24h 缓存命中），跳过网络预热（R5-2-3）",
                                _age,
                            )
                            _mark["done"] = True
                            _mark["success"] = True
                            return
                if not _cache_hit:
                    await asyncio.wait_for(get_global_indices(), timeout=15)
                    _mark["done"] = True
                    _mark["success"] = True
                    logger.info("全球指数缓存预热完成（网络拉取）")
            except (Exception, asyncio.CancelledError):
                _mark["done"] = True
                _mark["success"] = False
                logger.exception("全球指数缓存预热失败（非交易时段正常）")
    # R56 (round28): 删除独立启动 global_indices 预热 task（旧逻辑残留）——
    # _warmup_sequence_task 的 sequence 内已包含 global_indices 预热（:334）。
    # 两者并发启动、同时 miss 24h 缓存 → 各自网络拉取 → 预热 18.4s 双重执行回归
    # （warmup_timing.json 两条记录）。F3 重构（5b0c2fa）时遗漏删除旧独立 task
    # 是「重构遗漏」典型；此处只保留 sequence 调用。

    # 启动时预热 ETF 缓存（非阻塞），带超时保护
    async def _warmup_etf_cache():
        with warmup_timer("warmup_etf_cache", "warmup", "ETF 扫描预热"):
            _mark = app.state.warmup["etf_cache"]
            try:
                from app.fetchers.etf_scanner import fetch_all_etfs_base
                from .core.async_utils import run_sync
                result = await run_sync(fetch_all_etfs_base, timeout=120)
                _mark["done"] = True
                _mark["success"] = bool(result)
                if result:
                    logger.info("ETF cache warmup done: %d items", len(result))
            except asyncio.TimeoutError:
                _mark["done"] = True
                _mark["success"] = False
                logger.warning("ETF full scan timed out (120s), will complete on demand")
            except Exception as e:
                _mark["done"] = True
                _mark["success"] = False
                logger.warning("ETF cache warmup failed: %s", e)

    # O2 (round7 §7 P2): 预热任务串行化——旧实现 4 个重 IO 任务（market_cache /
    # etf_cache / global_indices / instruments_sync）同时 create_task，各自内部
    # 8 并发 run_sync + 全量扫描 + akshare 分页叠加 → 预热高峰 shared_executor
    # 64/64 饱和（round7 P2 复现）。改为一个编排任务按顺序串行执行（前一个
    # 完成后启动下一个），内部并发上限不变；每个子任务自带超时/失败隔离。
    # round25 R32: 预热覆盖冷拉取路径——板块缓存（sectors/heat + 板块动量 +
    # 热点板块）首个请求不再冷拉 4.7s（旧实现 60s 循环首次触发在启动后 ~10s+，
    # 首个用户请求仍可能撞冷缓存）。
    async def _warmup_sector_cache():
        # R44 (round27): 板块缓存预热改后台异步——不再阻塞 startup 就绪。
        # 旧实现 await refresh_sector_cache()，非交易时段/源冷却时该调用失败
        # （Connection aborted）仍耗 12.8s 空转，拖长整体预热（34.5s 回归）。
        # 改为：启动后台任务填充 sector cache，本函数立即返回，startup 不被拖长；
        # 失败仅 DEBUG/WARNING，不崩溃、不影响其它预热步骤。
        try:
            from .tasks.sector_refresh import refresh_sector_cache

            async def _do_sector_warmup():
                try:
                    await asyncio.wait_for(refresh_sector_cache(), timeout=15)
                    logger.info("板块缓存预热完成（后台）")
                except (Exception, asyncio.CancelledError) as exc:
                    logger.debug("板块缓存预热失败（后台，非阻塞）：%s", exc)

            # 不 await：立即返回让 startup 就绪；实际刷新在后台进行
            task = asyncio.create_task(_do_sector_warmup())
            # 持有强引用防止事件循环 GC 回收未完成的后台任务
            app.state._sector_warmup_task = task
            logger.info("板块缓存预热已在后台启动（非阻塞，R44）")
        except (Exception, asyncio.CancelledError) as exc:
            logger.warning("板块缓存预热任务启动失败（非阻塞）：%s", exc)

    # R59④ (round28): 设计链路数据预热——候选池 K 线缓存 + 因子矩阵。
    # 旧实现 design 首呼撞冷 K 线缓存（refresh_kline 42-75s 全量建库）+ 数据源冷却
    # → 90s 硬预算被吃光（round28 §14.4 task 559 超时失败）。sequence 末尾执行
    # （此刻 pool 已由 _warmup_market_cache 填充），预算 25s 内完成 K 线缓存刷新，
    # 使启动后首呼 design refresh ≤10s（热缓存）。后台 + 失败仅 WARNING 不阻塞启动。
    async def _warmup_design_data():
        try:
            from .services.market_data_hub import market_data_hub

            async def _do_design_warmup():
                _mark = app.state.warmup.setdefault("design_data", {
                    "done": False, "success": False, "label": "设计数据（K线/因子）",
                })
                try:
                    # 0. 等行情缓存预热任务收敛（refresh_market_cache 只刷实时报价，不填
                    #    pool——但先让它跑完可减少启动期数据源并发争抢；150s 上限，超时
                    #    仅 DEBUG，不阻塞 startup）。
                    _mkt_task = getattr(app.state, "_market_warmup_task", None)
                    if _mkt_task is not None:
                        try:
                            await asyncio.wait_for(asyncio.shield(_mkt_task), timeout=150)
                        except (Exception, asyncio.CancelledError):
                            logger.debug("[warmup] market warmup task wait timed out/failed (non-fatal)")
                    # 1. refresh() 填充候选池——**唯一真实入口**（round28 实测：等 market
                    #    warmup + 轮询 pool 恒空跳过，因为 refresh_market_cache 不写 _pool）。
                    #    预算 150s 覆盖 scanner(≤90s)+分类+索引重建；失败仅降级跳过。
                    try:
                        await asyncio.wait_for(market_data_hub.refresh(), timeout=150)
                    except (Exception, asyncio.CancelledError) as exc:
                        logger.debug("[warmup] design-data refresh failed/timed out (non-fatal): %s", exc)
                    # 2. 候选池读取（refresh 完成后 pool 已填充；冷却/TTL 跳过则用旧 pool）
                    _syms: list[str] = []
                    for _attempt in range(4):
                        try:
                            _pool = market_data_hub.get_pool()
                            _syms = list({str(it.get("symbol")) for layer in _pool.values()
                                          if isinstance(_pool, dict) and isinstance(layer, list)
                                          for it in layer if it.get("symbol") not in ("CASH",)})
                        except Exception:
                            _syms = []
                        if _syms:
                            break
                        await asyncio.sleep(2.0)
                    if not _syms:
                        logger.debug("[warmup] design-data warmup skipped: pool empty after refresh")
                        _mark["done"] = True
                        _mark["success"] = False
                        return
                    # 3. K 线缓存（磁盘缓存命中时秒级返回；miss 时 Semaphore(5) 并发拉取）
                    await asyncio.wait_for(market_data_hub.refresh_kline(_syms[:30]), timeout=25)
                    # 4. 因子矩阵预计算（factor_scores 随 pool 项挂载，无需单独预热——
                    #    refresh_kline 已使 get_factor_matrix 首个调用命中缓存）
                    _mark["done"] = True
                    _mark["success"] = True
                    logger.info("[warmup] design-data warmup done: %d pool symbols kline cached (R59④)",
                                len(_syms))
                except (Exception, asyncio.CancelledError) as exc:
                    _mark["done"] = True
                    _mark["success"] = False
                    logger.debug("[warmup] design-data warmup failed (non-fatal): %s", exc)

            # 不 await：立即返回让 startup 就绪；实际预热在后台进行
            task = asyncio.create_task(_do_design_warmup())
            app.state._design_warmup_task = task
            logger.info("设计数据预热已在后台启动（非阻塞，R59④）")
        except (Exception, asyncio.CancelledError) as exc:
            logger.warning("设计数据预热任务启动失败（非阻塞）：%s", exc)

    async def _warmup_sequence_task():
        # F3b (round27): 预热预算门禁——非阻塞 WARN。round27 §13.6 指出预热 profiler
        # 只写报告、无预算断言，导致 20s→34.5s 回归未被拦截。此处记录总耗时，超过
        # 阈值即结构化告警（不阻断启动、不影响请求），便于后续回归被捕获。
        # 阈值 30s：给 etf/instruments 冷拉（各自 90-120s 超时上限）留余量，
        # 同时能抓到「24s 快照 + 12.8s 空转」这类异常膨胀（34.5s 必触发）。
        _seq_start = time.time()
        try:
            await _run_warmup_sequence([
                _warmup_market_cache(),
                _warmup_etf_cache(),
                _warmup_global_indices(),
                _warmup_sector_cache(),
                _background_instruments_sync(),
                _background_indices_meta_sync(),
                # R59④ (round28): 设计链路数据预热——候选池 K 线缓存 + 因子矩阵。
                # 旧实现 design 首呼撞冷 K 线缓存（refresh_kline 42-75s 全量建库）
                # + 预热未完成时数据源冷却 → 90s 硬预算被吃光（task 559 超时失败）。
                # 预热 sequence 末尾执行（此刻 pool 已由 _warmup_market_cache 填充），
                # 后台 + 短预算（不阻塞 startup 就绪，失败仅 WARNING）。
                _warmup_design_data(),
            ])
        finally:
            _seq_elapsed = time.time() - _seq_start
            _WARMUP_BUDGET_S = float(os.environ.get("WARMUP_BUDGET_S", "30"))
            if _seq_elapsed > _WARMUP_BUDGET_S:
                logger.warning(
                    "[warmup-budget] 预热总耗时 %.1fs 超过预算阈值 %.1fs，可能存在回归"
                    "（盘后/源冷却或某数据源空转）——见 logs/warmup_timing.json（PROFILE_WARMUP=1）",
                    _seq_elapsed, _WARMUP_BUDGET_S,
                )
            else:
                logger.info("[warmup-budget] 预热总耗时 %.1fs（阈值 %.1fs，达标）",
                            _seq_elapsed, _WARMUP_BUDGET_S)

    if _SKIP_WARMUP:
        logger.info("[lifespan] ETF_SURGE_SKIP_WARMUP=1, 跳过后台预热任务（快速启动模式）")
    else:
        _warmup_tasks.append(asyncio.create_task(_warmup_sequence_task()))

    # Scheduler temporarily disabled for diagnostics (design-check-pipeline-redesign)
    # try:
    #     async def _scheduler_wrapper():
    #         try:
    #             await asyncio.wait_for(refresh_market_cache(), timeout=25)
    #         except (Exception, asyncio.CancelledError):
    #             logger.exception("定时刷新行情缓存失败")
    # 
    #     async def _news_scheduler_wrapper():
    #         try:
    #             await asyncio.wait_for(refresh_news_cache(), timeout=30)
    #         except (Exception, asyncio.CancelledError):
    #             logger.exception("定时刷新资讯缓存失败")
    # 
    #     from apscheduler.schedulers.asyncio import AsyncIOScheduler
    #     scheduler = AsyncIOScheduler()
    #     scheduler.add_job(_scheduler_wrapper, "interval", seconds=15, id="refresh_market_cache", max_instances=1, coalesce=True)
    #     scheduler.add_job(_news_scheduler_wrapper, "interval", seconds=30, id="refresh_news_cache", max_instances=1, coalesce=True)
    #     scheduler.start()
    #     app.state.scheduler = scheduler

    # Start health probe loop
    asyncio.create_task(health_loop(interval=120.0))

    # Start sector cache refresh loop (60s, Phase 2)
    async def _sector_refresh_loop():
        # 延迟 10s 首轮执行，让 ETF / 指数预热优先完成
        await asyncio.sleep(10)
        while True:
            try:
                await asyncio.wait_for(refresh_sector_cache(), timeout=20)
            except (Exception, asyncio.CancelledError):
                logger.warning("[lifespan] sector refresh cycle failed, will retry")
            await asyncio.sleep(60)
    asyncio.create_task(_sector_refresh_loop())
    logger.info("板块缓存刷新循环已启动（60s）")

    # Start regime + sentiment refresh loop (120s, Phase 2.7.9)
    async def _regime_sentiment_refresh_loop():
        while True:
            try:
                from .services.market_data_hub import market_data_hub
                await asyncio.wait_for(market_data_hub.update_market_regime(), timeout=15)
                await asyncio.wait_for(market_data_hub.refresh_sentiment_cache(), timeout=15)
            except (Exception, asyncio.CancelledError):
                logger.warning("[lifespan] regime/sentiment refresh cycle failed, will retry")
            await asyncio.sleep(120)
    asyncio.create_task(_regime_sentiment_refresh_loop())
    logger.info("市态+情绪缓存刷新循环已启动（120s）")

    # Start news refresh loop (120s, v6 Phase 1: news aggregation cache)
    async def _news_refresh_loop():
        while True:
            try:
                from .services.market_data_hub import market_data_hub
                await asyncio.wait_for(asyncio.to_thread(market_data_hub.refresh_news), timeout=20)
                # R5-1-1: 预热期 LLM 错峰——预热完成前跳过 LLM 附属调用（news 摘要）。
                # 旧逻辑启动即触发 enrich_news_summaries → 与设计任务并发打满 DeepSeek
                # 配额 → 429（F3-6 退避在 45s DATA 预算内来不及）。预热完成后才恢复。
                _warmup_done = all(
                    v.get("done") for v in getattr(app.state, "warmup", {}).values()
                )
                if _warmup_done:
                    # Z18: 后台为重要新闻生成 AI 摘要（不阻塞刷新循环，失败静默）
                    asyncio.create_task(market_data_hub.enrich_news_summaries())
                else:
                    logger.info("[lifespan] warmup in progress — skipping LLM news summaries (R5-1-1)")
            except (Exception, asyncio.CancelledError):
                logger.warning("[lifespan] news refresh cycle failed, will retry")
            await asyncio.sleep(120)
    asyncio.create_task(_news_refresh_loop())
    logger.info("资讯缓存刷新循环已启动（120s）")

    app.state.scheduler = None  # Scheduler disabled for diagnostics

    # 崩溃恢复：扫描 report_quality="pending" 且创建 >5min 的记录，标记为 fallback
    try:
        async def _recover_stale_designs():
            from sqlalchemy import select
            from datetime import datetime, timedelta
            from .models.portfolio_design import PortfolioDesign
            from .database import async_session

            cutoff = datetime.utcnow() - timedelta(minutes=5)
            async with async_session() as db:
                stale = await db.execute(
                    select(PortfolioDesign).where(
                        PortfolioDesign.report_quality == "pending",
                        PortfolioDesign.created_at < cutoff,
                    )
                )
                count = 0
                for design in stale.scalars().all():
                    design.report_quality = "fallback"
                    count += 1
                if count:
                    await db.commit()
                    logger.info("[recovery] marked %d stale design(s) as fallback (crashed before LLM report)", count)
                else:
                    logger.info("[recovery] no stale designs to recover")
        await _recover_stale_designs()
    except Exception as exc:
        logger.warning("[recovery] failed to scan stale designs: %s", exc)

    # A04 (Z27 重写): 启动时收敛遗留的非终态任务（进程已死，任务不可能继续执行）
    # DB-backed: 所有 pending/running/quick_ready → failed + error_message，诚实收敛状态
    try:
        async def _cleanup_stuck_tasks():
            from datetime import datetime
            from sqlalchemy import select
            from .models.task import TaskRecord
            from .database import async_session

            async with async_session() as db:
                stuck = (await db.execute(
                    select(TaskRecord).where(
                        TaskRecord.status.in_(["pending", "running", "quick_ready"])
                    )
                )).scalars().all()
                for t in stuck:
                    t.status = "failed"
                    t.error_message = "后端重启，任务中断（未完成），请重新提交"
                    t.completed_at = datetime.utcnow()
                if stuck:
                    await db.commit()
                    logger.info("[recovery] marked %d stuck task(s) as failed on startup", len(stuck))
                else:
                    logger.info("[recovery] no stuck tasks found on startup")
        await _cleanup_stuck_tasks()
    except Exception as exc:
        logger.warning("[recovery] failed to cleanup stuck tasks: %s", exc)

    # Start IC persistence loop (120s, B1)
    async def _ic_persistence_loop():
        from .factors.ic_tracker import ic_tracker
        from .factors.factor_registry import registry
        from .database import async_session

        await asyncio.sleep(30)  # delay first run
        while True:
            try:
                ic_batch = getattr(registry, "_last_ic_batch", None)
                if ic_batch and len(ic_batch) > 0:
                    async with async_session() as db:
                        count = await ic_tracker.save_ic_batch_to_db(db, ic_batch)
                    if count:
                        logger.info("[ic_persistence] saved %d IC records", count)
                else:
                    logger.debug("[ic_persistence] no IC data to persist")
            except Exception as exc:
                logger.warning("[ic_persistence] cycle failed: %s", exc)
            # round15 方案三阶段一: 落库后刷新 IC 序列缓存（aggregate_factor_scores
            # IC 加权聚合的数据源；失败回退等权，不阻塞）
            try:
                async with async_session() as db:
                    await registry.refresh_ic_series(db)
            except Exception as exc:
                logger.warning("[ic_persistence] IC series refresh failed: %s", exc)
            # R5-1-5: 周期 compute（复用 K 线缓存，不触网）——IC 非请求驱动，
            # 重启后无请求也会更新 _last_ic_batch（B1 验收达标）。
            try:
                from .factors.factor_registry import registry as _reg
                from .services.market_data_hub import market_data_hub as _hub
                _pool = _hub.get_pool()
                _syms = [it.get("symbol") for layer in _pool.values() if isinstance(_pool, dict)
                         for it in layer if it.get("symbol") not in ("CASH",)]
                # 复用列式 K 线缓存（_kline_cache，S5 同一数据源），不触网
                _kline = getattr(_hub, "_kline_cache", None)
                if _syms and _kline:
                    # round14 P2-Z 修复 2: IC 循环补 symbol_extra 注入（benchmark_close/
                    # shares_change_20d）——旧实现完全不调 enrich，tracking_error/shares_change
                    # 两因子对每只 ETF 返回 0.0 → compute_periodic_ic 永不产出 IC（§2.11）。
                    # 独立 try/except + 15s 短超时（_enrich_symbol_extra 内部 60s 预算 >
                    # IC 循环 30s，防 enrich 触网慢耗尽整个 IC 循环预算连累其余 31 因子）。
                    _symbol_extra = {}
                    try:
                        _symbol_extra = await asyncio.wait_for(
                            _hub._enrich_symbol_extra(_syms, {}),
                            timeout=15,
                        )
                    except (Exception, asyncio.CancelledError) as _exc:
                        logger.debug("[ic_persistence] symbol_extra enrich skipped: %s", _exc)
                    await asyncio.wait_for(
                        _reg.compute(_syms, market_data=_kline, symbol_extra=_symbol_extra),
                        timeout=30,
                    )
            except (Exception, asyncio.CancelledError) as exc:
                logger.debug("[ic_persistence] periodic compute skipped: %s", exc)
            await asyncio.sleep(120)

    asyncio.create_task(_ic_persistence_loop())
    logger.info("IC 持久化循环已启动（120s）")

    # R55 (round27): 一次性 IC 历史回填（startup-once，非阻塞）。
    # 复用 K 线缓存时光回溯重放因子分，对每个历史交易日算截面 IC 批量落库，
    # 使 factor_ic_records.distinct trade_date 从 3 跳升至 ~239（≥60 →「可观察」，
    # 自然积累到 250 →「有效」，符合用户「接受等自然积累」决策）。
    # MIN_TRADING_DAYS 门槛不变（诚实，不谎报 valid）。
    # 仅当 K 线缓存就绪且尚未回填时执行；失败仅 WARNING，不影响启动。
    async def _backfill_ic_history_task():
        from .factors.ic_tracker import ic_tracker
        from .factors.factor_registry import registry as _reg
        from .services.market_data_hub import market_data_hub as _hub
        from .database import async_session

        # 等 K 线缓存就绪（refresh_kline 在行情预热中填充，约 10-20s）
        # R58 (round28): 旧实现等 20s 后只检查一次，未就绪即「永久跳过」——
        # startup 时 K 线预热未完成（refresh_kline 42-75s 冷建库），回填任务
        # 跳过即永不再试，factor_ic_records 恒 4 个 trade_date。改为**延迟 + 重试**：
        # 未就绪时退避等待（30s/60s/120s）重试 ≤3 次，K 线就绪或预热完成后补跑。
        # 仍不就绪才诚实放弃（WARNING），不静默跳过。重试逻辑提取为模块级
        # _wait_for_kline_rows（可单测，round28 §12 防护缺口 3）。
        _IC_BACKFILL_MAX_RETRIES = 3
        _IC_BACKFILL_RETRY_DELAYS = (30.0, 60.0, 120.0)
        rows = await _wait_for_kline_rows(
            _hub,
            initial_sleep=20.0,
            retry_delays=_IC_BACKFILL_RETRY_DELAYS,
            max_retries=_IC_BACKFILL_MAX_RETRIES,
        )
        try:
            if not rows:
                logger.warning(
                    "[ic_backfill] K 线缓存未就绪（重试 %d 次后放弃），历史回填跳过——"
                    "预热未完成或 refresh_kline 未执行（R58）",
                    _IC_BACKFILL_MAX_RETRIES,
                )
                return
            # 防重复回填：已回填（≥200 交易日）则跳过
            async with async_session() as db:
                _existing = await ic_tracker.count_distinct_trade_dates(db)
            if _existing >= 200:
                logger.info("[ic_backfill] 已回填（%d 交易日），跳过", _existing)
                return
            # 取池内 symbol（与持久化循环一致）——R58 延伸：磁盘 K 线缓存使 kline 门
            # 秒过，但启动时组合池尚未由设计数据预热填充（refresh() 60-90s），旧实现
            # 「组合池为空，跳过」恒跳过。改为轮询等待 pool 就绪（≤6×20s=120s）。
            _syms = await _wait_for_pool_symbols(_hub)
            if not _syms:
                logger.info("[ic_backfill] 组合池长时间为空（等待后放弃），跳过")
                return
            # 构造列式 K 线（时序升序）+ dates
            kline: dict[str, dict] = {}
            for sym, rws in rows.items():
                if sym not in _syms or not isinstance(rws, list) or not rws:
                    continue
                closes = [r.get("close") for r in rws if r.get("close") is not None]
                dates = [r.get("date") for r in rws if r.get("close") is not None]
                if len(closes) >= 5:
                    kline[sym] = {"close": closes, "dates": dates}
            if len(kline) < 3:
                logger.info("[ic_backfill] K 线标的不足 3 只，跳过")
                return
            # symbol_extra（静态，不时光回溯；触网失败则空，因子分降级但可算）
            _symbol_extra: dict = {}
            try:
                _symbol_extra = await asyncio.wait_for(
                    _hub._enrich_symbol_extra(_syms, {}), timeout=15
                )
            except (Exception, asyncio.CancelledError) as _e:
                logger.debug("[ic_backfill] symbol_extra enrich skipped: %s", _e)
            # 时光回溯：逐历史交易日重放因子分
            n = max(len(k["close"]) for k in kline.values())
            factor_scores_by_index: dict[int, dict] = {}
            # 快照实时 IC 状态，回填后还原（避免 240 次 compute 污染 _last_ic_batch）
            _snap_batch = getattr(_reg, "_last_ic_batch", None)
            _snap_at = getattr(_reg, "_last_computed_at", None)
            try:
                for i in range(n - 1, 0, -1):
                    # R58 修复延伸: compute() 在 market_data 注入时是纯同步 CPU 计算
                    #（无 await，因子 pandas 数学），499 次迭代连续执行会长时间独占事件
                    # 循环 → /health 等请求超时。每次迭代让出控制权，保持服务可响应。
                    await asyncio.sleep(0)
                    truncated: dict[str, dict] = {}
                    for sym, kd in kline.items():
                        if i < len(kd["close"]):
                            # 同 _slice_market_data_day 取向：时序升序切片 recent-first 传入 compute
                            tail = kd["close"][: i + 1]
                            truncated[sym] = {
                                "close": list(reversed(tail)),
                                "open": list(reversed(kd["open"][: i + 1])) if kd.get("open") else [],
                                "high": list(reversed(kd["high"][: i + 1])) if kd.get("high") else [],
                                "low": list(reversed(kd["low"][: i + 1])) if kd.get("low") else [],
                                "volume": list(reversed(kd["volume"][: i + 1])) if kd.get("volume") else [],
                            }
                    if len(truncated) < 3:
                        continue
                    try:
                        fs = await asyncio.wait_for(
                            _reg.compute(_syms, market_data=truncated, symbol_extra=_symbol_extra),
                            timeout=10,
                        )
                    except (Exception, asyncio.CancelledError):
                        continue
                    factor_scores_by_index[i] = {s: fs[s] for s in truncated}
            finally:
                _reg._last_ic_batch = _snap_batch
                _reg._last_computed_at = _snap_at
            # 批量落库
            async with async_session() as db:
                cnt = await ic_tracker.backfill_ic_history(db, kline, factor_scores_by_index)
            logger.info("[ic_backfill] 历史回填完成：%d 个交易日", cnt)
            # 回填后刷新 IC 序列缓存（供 /factors/active 加权聚合）
            try:
                async with async_session() as db:
                    await _reg.refresh_ic_series(db)
            except Exception as _e:
                logger.debug("[ic_backfill] refresh_ic_series failed: %s", _e)
        except Exception as exc:
            logger.warning("[ic_backfill] 历史回填失败（非致命）：%s", exc)

    asyncio.create_task(_backfill_ic_history_task())
    logger.info("IC 历史回填任务已启动（startup-once，非阻塞，R55）")

    # R5-1-5: 启动时从 DB 恢复 _last_ic_batch（IC 非请求驱动——重启后
    # /factors/active 不依赖任何请求即返回非空）。失败仅 WARNING，不阻塞启动。
    try:
        from .factors.factor_registry import registry as _ic_registry
        from .database import async_session as _ic_session

        async with _ic_session() as _db:
            _restored = await _ic_registry.restore_ic_from_db(_db)
            # round15 方案三阶段一: 启动时一并加载 IC 序列缓存（IC 加权聚合数据源）
            await _ic_registry.refresh_ic_series(_db)
        if _restored:
            logger.info("[ic_restore] restored %d IC entries at startup (R5-1-5)", _restored)
        else:
            logger.info("[ic_restore] no historical IC found at startup (R5-1-5)")
    except Exception as exc:
        logger.warning("[ic_restore] IC restore failed (non-fatal): %s", exc)

    # A1-A2: Wait for warmup tasks to complete before stopping profiler
    if _warmup_tasks:
        logger.info("[warmup] Waiting for %d warmup task(s) to complete...", len(_warmup_tasks))
        done, pending = await asyncio.wait(_warmup_tasks, timeout=60)
        completed = len(done)
        timed_out = len(pending)
        logger.info("[warmup] %d task(s) completed, %d still pending (will continue in background)", completed, timed_out)

    if _PROFILE_WARMUP:
        assert _profiler is not None  # type narrowing for mypy
        _profiler.disable_pyinstrument()
        _profiler.disable_cprofile()
        _profiler.print_summary()
        _profiler.write_report("warmup_timing.json")
        logger.info("[profiler] Warmup profiling complete — reports saved to logs/")

    # ── Warmup degradation alert (7.5 P2) ────────────────────────────
    _warmup_duration = time.time() - getattr(app.state, "_startup_ts", time.time())
    if _warmup_duration > 30:
        logger.warning(
            "[warmup] Warmup took %.1fs (threshold 30s) — degradation possible. "
            "Check data source health and network latency.",
            _warmup_duration,
        )
    elif _warmup_duration > 15:
        logger.info(
            "[warmup] Warmup took %.1fs — within acceptable range.",
            _warmup_duration,
        )
    else:
        logger.info("[warmup] Warmup completed in %.1fs.", _warmup_duration)

    yield

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)
    await token_store.shutdown()
    await source_event_store.shutdown()
    logger.info("应用已关闭")


app = FastAPI(title="ETF Surge API", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    access_logger = get_logger("api.access")
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start) * 1000
        access_logger.exception(
            "请求异常 %s %s (%.1fms)", request.method, request.url.path, duration_ms
        )
        raise
    duration_ms = (time.perf_counter() - start) * 1000
    access_logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(portfolio.router)
app.include_router(analysis.router)
app.include_router(news.router)
app.include_router(ws.router)
app.include_router(admin.router)
app.include_router(factors.router)
app.include_router(system.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

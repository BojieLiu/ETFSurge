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
    from .services.source_registry import registry
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

    # 启动时后台预热行情缓存（不阻塞启动，10s 超时 → 部分数据可接受）
    async def _warmup_market_cache():
        with warmup_timer("warmup_market_cache", "warmup", "行情缓存预热"):
            _mark = app.state.warmup["market_cache"]
            try:
                await asyncio.wait_for(refresh_market_cache(), timeout=10)
                _mark["done"] = True
                _mark["success"] = True
                logger.info("行情缓存预热完成")
            except (Exception, asyncio.CancelledError):
                _mark["done"] = True
                _mark["success"] = False
                logger.exception("行情缓存预热失败（不影响启动）")

    _warmup_tasks.append(asyncio.create_task(_warmup_market_cache()))

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
                    os.path.dirname(os.path.dirname(__file__)),
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
    _warmup_tasks.append(asyncio.create_task(_warmup_global_indices()))

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
    _warmup_tasks.append(asyncio.create_task(_warmup_etf_cache()))

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
                    await asyncio.wait_for(
                        _reg.compute(_syms, market_data=_kline),
                        timeout=30,
                    )
            except (Exception, asyncio.CancelledError) as exc:
                logger.debug("[ic_persistence] periodic compute skipped: %s", exc)
            await asyncio.sleep(120)

    asyncio.create_task(_ic_persistence_loop())
    logger.info("IC 持久化循环已启动（120s）")

    # R5-1-5: 启动时从 DB 恢复 _last_ic_batch（IC 非请求驱动——重启后
    # /factors/ic 不依赖任何请求即返回非空）。失败仅 WARNING，不阻塞启动。
    try:
        from .factors.factor_registry import registry as _ic_registry
        from .database import async_session as _ic_session

        async with _ic_session() as _db:
            _restored = await _ic_registry.restore_ic_from_db(_db)
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

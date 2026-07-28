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

    # 启动时后台预热行情缓存（不阻塞启动，25s 超时）
    async def _warmup_market_cache():
        with warmup_timer("warmup_market_cache", "warmup", "行情缓存预热"):
            _mark = app.state.warmup["market_cache"]
            try:
                await asyncio.wait_for(refresh_market_cache(), timeout=25)
                _mark["done"] = True
                _mark["success"] = True
                logger.info("行情缓存预热完成")
            except (Exception, asyncio.CancelledError):
                _mark["done"] = True
                _mark["success"] = False
                logger.exception("行情缓存预热失败（不影响启动）")

    _warmup_tasks.append(asyncio.create_task(_warmup_market_cache()))

    # 启动时预热全球指数缓存（非阻塞，写入持久化 cache，重启后不丢失）
    async def _warmup_global_indices():
        with warmup_timer("warmup_global_indices", "warmup", "全球指数缓存预热"):
            _mark = app.state.warmup["global_indices"]
            try:
                from .services.market_service import get_global_indices
                await asyncio.wait_for(get_global_indices(), timeout=30)
                _mark["done"] = True
                _mark["success"] = True
                logger.info("全球指数缓存预热完成")
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
                from .services.pool_manager import pool_manager
                await asyncio.wait_for(pool_manager.update_market_regime(), timeout=15)
                await asyncio.wait_for(pool_manager.refresh_sentiment_cache(), timeout=15)
            except (Exception, asyncio.CancelledError):
                logger.warning("[lifespan] regime/sentiment refresh cycle failed, will retry")
            await asyncio.sleep(120)
    asyncio.create_task(_regime_sentiment_refresh_loop())
    logger.info("市态+情绪缓存刷新循环已启动（120s）")

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

    # A04: 启动时清理积压的 stuck 任务（旧 session 遗留的 "running" 任务）
    # 找出所有 status="running" 且创建时间 > 5min 的任务，标记为 failed
    try:
        async def _cleanup_stuck_tasks():
            from .tasks.task_manager import task_manager as _tm
            stuck_count = 0
            for tid, t in list(_tm._tasks.items()):
                if t.get("status") == "running":
                    created = t.get("created_at", "")
                    try:
                        from datetime import datetime as _dt
                        created_dt = _dt.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
                        if (datetime.utcnow() - created_dt).total_seconds() > 300:
                            _tm.update_task(tid, status="failed", progress=0,
                                            error_message="启动时清理：任务超时（旧 session 遗留）")
                            stuck_count += 1
                    except (ValueError, Exception):
                        _tm.update_task(tid, status="failed", progress=0,
                                        error_message="启动时清理：任务状态异常")
                        stuck_count += 1
            if stuck_count:
                logger.info("[recovery] cleaned up %d stuck task(s) on startup", stuck_count)
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
            await asyncio.sleep(120)

    asyncio.create_task(_ic_persistence_loop())
    logger.info("IC 持久化循环已启动（120s）")

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

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .services.cache_service import redis_cache
from .tasks.market_refresh import refresh_market_cache
from .tasks.news_refresh import refresh_news_cache
from .monitor.token_usage import token_store
from .core.logging import get_logger, setup_logging
from .routers import market, portfolio, analysis, news, ws, admin
from .services.source_health import health_loop

logger = get_logger("lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("应用启动中…")
    await init_db()
    await redis_cache.init()

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

    # 启动时后台预热行情缓存（不阻塞启动，25s 超时）
    async def _warmup_market_cache():
        try:
            await asyncio.wait_for(refresh_market_cache(), timeout=25)
            logger.info("行情缓存预热完成")
        except (Exception, asyncio.CancelledError):
            logger.exception("行情缓存预热失败（不影响启动）")

    asyncio.create_task(_warmup_market_cache())

    # 启动时预热全球指数缓存（非阻塞，写入持久化 cache，重启后不丢失）
    async def _warmup_global_indices():
        try:
            from .services.market_service import get_global_indices
            await asyncio.wait_for(get_global_indices(), timeout=30)
            logger.info("全球指数缓存预热完成")
        except (Exception, asyncio.CancelledError):
            logger.exception("全球指数缓存预热失败（非交易时段正常）")
    asyncio.create_task(_warmup_global_indices())

    # 启动时预热 ETF 缓存（非阻塞）
    async def _warmup_etf_cache():
        try:
            from app.fetchers.etf_scanner import fetch_all_etfs_base
            result = await asyncio.to_thread(fetch_all_etfs_base)
            if result:
                logger.info("ETF 缓存预热完成：%d 只", len(result))
        except Exception:
            logger.warning("ETF 缓存预热失败（不影响启动）")
    asyncio.create_task(_warmup_etf_cache())

    try:
        async def _scheduler_wrapper():
            try:
                await asyncio.wait_for(refresh_market_cache(), timeout=25)
            except (Exception, asyncio.CancelledError):
                logger.exception("定时刷新行情缓存失败")

        async def _news_scheduler_wrapper():
            try:
                await asyncio.wait_for(refresh_news_cache(), timeout=30)
            except (Exception, asyncio.CancelledError):
                logger.exception("定时刷新资讯缓存失败")

        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_scheduler_wrapper, "interval", seconds=15, id="refresh_market_cache", max_instances=1, coalesce=True)
        scheduler.add_job(_news_scheduler_wrapper, "interval", seconds=30, id="refresh_news_cache", max_instances=1, coalesce=True)
        scheduler.start()
        app.state.scheduler = scheduler
        # Start health probe loop
        asyncio.create_task(health_loop(interval=120.0))
        logger.info("调度器已启动（行情 15s / 资讯 30s）")
    except Exception:
        logger.exception("调度器初始化失败")
        app.state.scheduler = None

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


@app.get("/health")
async def health():
    return {"status": "ok"}

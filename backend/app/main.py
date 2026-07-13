from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import init_db
from .services.cache_service import redis_cache
from .tasks.market_refresh import refresh_market_cache
from .routers import market, portfolio, analysis, news, ws


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await redis_cache.init()

    try:
        import asyncio
        async def _scheduler_wrapper():
            try:
                await asyncio.wait_for(refresh_market_cache(), timeout=12)
            except (asyncio.TimeoutError, Exception):
                pass
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        scheduler = AsyncIOScheduler()
        scheduler.add_job(_scheduler_wrapper, "interval", seconds=15, id="refresh_market_cache", max_instances=1, coalesce=True)
        scheduler.start()
        app.state.scheduler = scheduler
    except Exception:
        app.state.scheduler = None

    yield

    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)

app = FastAPI(title="ETF Surge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market.router)
app.include_router(portfolio.router)
app.include_router(analysis.router)
app.include_router(news.router)
app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

# round36 §8-B: 看门狗转储目录——模块级计算（ASYNC240：避免在 async lifespan
# 内做同步 Path.resolve；导入期一次性求值，运行期零开销）
_LOOP_WATCHDOG_DUMP_DIR = str(Path(__file__).resolve().parent.parent.parent / "logs")
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .core.logging import get_logger, setup_logging
from .database import init_db
from .monitor.token_usage import token_store
from .routers import admin, analysis, factors, market, news, portfolio, system, ws
from .services.cache_service import redis_cache
from .services.source_health import health_loop
from .tasks.market_refresh import refresh_market_cache
from .tasks.sector_refresh import refresh_sector_cache

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


def _fast_json_enabled() -> bool:
    """R89 (round30): ETF_FAST_JSON 默认启用——akshare 的 demjson 纯 Python JSON
    解析是预热 CPU 热点（cProfile 21.6s，round30 §1 实证），fast_json shim
    （orjson/json strict-first）可安全消灭该热点。默认 on；显式
    `ETF_FAST_JSON=0|false|no|off` 关闭（保留 env 显式关闭，兼容旧 opt-in 语义）。
    """
    _v = os.environ.get("ETF_FAST_JSON", "").strip().lower()
    return _v not in ("0", "false", "no", "off")


if _PROFILE_WARMUP:
    from .profiling.warmup_profiler import (
        WarmupProfiler,
        get_warmup_profiler,
    )
    from .profiling.warmup_profiler import (
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


def _kline_depth_from_rows(rows: dict) -> int:
    """R103 (round34): K 线深度只统计「K 线行」——首行含非空 ``date`` 键的序列。

    场外联接基金净值序列（如 019633 联接 C，658 点、行无 date 键）不得计入：
    否则动态 skip 阈值 ``max(depth - 30, 200)`` 被 658 顶高至 628，DB 已回填的
    502 恒 < 628 → 每次启动重跑完整回填（~56s CPU 白跑）。判据与回填日期轴
    消费语义一致（本文件回填构造同取 ``r.get("date")``）；sina/baostock/netease
    路径行统一规整为 date 键（china_market._sina_history_cb 等），净值序列不受影响。
    """
    return max(
        (len(rws) for rws in rows.values()
         if isinstance(rws, list) and rws
         and str(rws[0].get("date") or "").strip()),
        default=0,
    )


def _ic_backfill_should_skip(existing_days: int, kline_depth: int) -> bool:
    """R102 动态 skip 门禁 + round34 实施轮 FORCE_IC_BACKFILL 一次性旁路。

    skip 判据 = 已回填 distinct 交易日 ≥ max(K 线深度-30, 200)。该信号感知不到
    per-factor 覆盖缺口（如 R108 五列修复后 OHLCV 因子仍无历史）——此类一次性
    全量重放用 ``ETF_SURGE_FORCE_IC_BACKFILL=1`` 旁路（upsert 幂等保证数据安全，
    重放完成后关闭即可恢复正常 skip 门禁）。
    """
    if os.environ.get("ETF_SURGE_FORCE_IC_BACKFILL", "") == "1":
        logger.info(
            "[ic_backfill] ETF_SURGE_FORCE_IC_BACKFILL=1 — bypass skip gate (one-shot replay)"
        )
        return False
    return existing_days >= max(kline_depth - 30, 200)


def _build_backfill_kline(rows: dict, syms) -> dict[str, dict]:
    """R102/R108: 构造列式回填 K 线（时序升序），带齐 OHLCV 五列。

    R108 (round34)：旧实现只装 {close, dates} 两键——缓存行内的 open/high/low/
    volume 被丢弃 → truncated 重放展开恒空数组 → atr/vol_ratio/vwap/
    amount_stability/kdj×3 七个纯 K 线因子历史恒无法入算。四列与 close **同条件**
    收集（``r.get("close") is not None``），列长恒等；sina 行五列齐全，
    truncated 展开（``kd["open"][:i+1] if kd.get("open")``）自此自然生效。
    """
    kline: dict[str, dict] = {}
    for sym, rws in rows.items():
        if sym not in syms or not isinstance(rws, list) or not rws:
            continue
        closes = [r.get("close") for r in rws if r.get("close") is not None]
        if len(closes) >= 5:
            kline[sym] = {
                "close": closes,
                "dates": [r.get("date") for r in rws if r.get("close") is not None],
                # R108: 四列与 close 同条件收集（列长恒等）
                "open": [r.get("open") for r in rws if r.get("close") is not None],
                "high": [r.get("high") for r in rws if r.get("close") is not None],
                "low": [r.get("low") for r in rws if r.get("close") is not None],
                "volume": [r.get("volume") for r in rws if r.get("close") is not None],
            }
    return kline


# R88 (round30): 个股 K 线缓存扩展——从 DB 持仓读取非 ETF 个股（A 股 600519 / HK
# 00700 / US AAPL），补入 K 线预热符号集（方案 A：复用 hub 缓存域，不新增第二缓存域）。
async def _kline_warmup_holdings_symbols() -> list[str]:
    """返回持仓中 asset_type 非 ETF 的个股代码（A/HK/US 混合）。

    design-data warmup 只预热 pool 内 ETF（round30 §14.5 实证个股 600519/AAPL
    不在 hub._kline_cache_rows → symbol-analysis R60 兜底取空 → 盘后 indicators
    data_available=false）。DB 不可用/空 → 返回 []（不影响 pool 预热）。
    """
    try:
        from sqlalchemy import select

        from app.database import async_session
        from app.models.portfolio import PortfolioETF

        async with async_session() as session:
            rows = (await session.execute(
                select(PortfolioETF.symbol, PortfolioETF.asset_type)
                .where(PortfolioETF.is_active == True)  # noqa: E712
            )).all()
        out: list[str] = []
        for sym, at in rows:
            if not sym:
                continue
            _at = str(at or "A").upper()
            if _at in ("ETF",):
                continue  # 个股段（A/HK/US/stock）才需补；ETF 已在 pool 内
            out.append(str(sym))
        return out
    except Exception as _e:
        logger.debug("[warmup] holdings symbols query failed (non-fatal): %s", _e)
        return []


async def _kline_warmup_symbols(pool_syms: list[str]) -> list[str]:
    """R88: K 线预热符号集 = pool ETF + 持仓个股（去重保序）。

    仅扩展「需要 K 线的非 ETF 个股」；持仓查询失败/空退化为纯 pool 集合（不回归）。
    """
    try:
        holdings = await _kline_warmup_holdings_symbols() or []
    except Exception as _e:
        logger.debug("[warmup] holdings symbols unavailable — using pool only: %s", _e)
        holdings = []
    merged = list(pool_syms) + [s for s in holdings if s not in pool_syms]
    return merged


# R89 (round30): concept/industry 全量列表后台预拉（模块级，可单测）。
async def _warmup_sector_lists() -> None:
    """预热概念/行业板块全量列表缓存（冷首呼 38.9s → 命中缓存）。

    不占 startup 关键路径（warmup 30s 预算外，§14.6 原则：就绪后后台异步预拉）。
    失败静默（首呼回源兜底）；run_sync_long 走长任务线程池（不阻塞事件循环）。
    """
    try:
        from .core.async_utils import run_sync_long
        from .fetchers.sector_fetcher import (
            fetch_concept_sectors,
            fetch_industry_sectors,
        )
        await asyncio.gather(
            run_sync_long(fetch_concept_sectors, 150, timeout=40),
            run_sync_long(fetch_industry_sectors, 80, timeout=40),
            return_exceptions=True,
        )
        logger.info("[warmup] sector list prefetch done (concept/industry, R89)")
    except Exception as _e:
        logger.debug("[warmup] sector list prefetch failed (non-fatal): %s", _e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("应用启动中…")

    # F11: fast JSON shim for akshare's demjson decoder.
    # R89 (round30): 默认启用（ETF_FAST_JSON 未设置/1/true/yes 均 on；仅显式
    # 0/false/no/off 关闭）——demjson 纯 Python 解析是预热 CPU 热点（round30 §1
    # cProfile 21.6s），shim 用 orjson/json strict-first 消灭该热点，安全降级原
    # demjson（非 strict 输入自动回退）。
    if _fast_json_enabled():
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

    # round46 §1: 启动期加载 LLM 排除项 (DB -> in-memory model_catalog._exclusions)
    # 持久化键格式 llm_excluded:<provider>:<model> (AppConfig 表); 由 admin
    # POST /api/v1/admin/llm-excluded 写入, DELETE 移除. 启动期灌回确保
    # 重启后熔断三件套护栏 3 仍生效 (R143 R&D 此前仅 in-memory, 重启清零).
    with warmup_timer("load_llm_excluded", "init", "Load LLM exclusions from DB"):
        from .core.config_manager import config_manager as _cm
        from .analysis.llm.model_catalog import model_catalog as _mc
        _db_keys = await _cm.list_keys_with_prefix("llm_excluded:")
        _loaded = _mc.load_excluded_from_keys(_db_keys)
        logger.info(
            "[lifespan] LLM exclusions loaded: %d/%d (DB keys scanned=%d)",
            _loaded, _loaded, len(_db_keys),
        )

    # Pre-import heavy modules to avoid blocking the event loop on first use
    logger.info("[lifespan] Pre-loading heavy modules (strategy_design, analysis)...")
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
    import asyncio

    from .core.source_registry import registry
    from .monitor.source_events import source_event_store

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
                # R5-2-3: 缓存命中即跳过（与 R4-26 失败缓存模式一致）——磁盘 last_ok
                # 缓存 24h 内有效时直接复用，不触网（旧逻辑仅 1h 内跳过 → 冷拉 1.09s 热点）。
                # R86 (round30): 落盘到 settings.data_dir（挂载卷），替代 dirname×3 的
                # 源码目录（容器内 `__file__×3` = `/` → `/data/indices_cache.json` 非挂载卷）。
                from app.config import settings as _st

                from .services.market_service import (
                    _GLOBAL_INDICES_OK_TTL,
                    _global_indices_last_ok,
                    _load_ok_cache,
                    get_global_indices,
                )
                # round36 ASYNC240 修复：os.path 元数据探测移入 to_thread（事件循环不阻塞）
                def _probe_ok_cache_mtime() -> float | None:
                    # round35 RC-C6: 落点单点收敛至 settings.data_dir——删除 dirname×3
                    # fallback（与 market_service.indices_cache 同源漂移，一并收口）。
                    _pp = os.path.join(str(getattr(_st, "data_dir", "")), "indices_cache.json")
                    return os.path.getmtime(_pp) if os.path.isfile(_pp) else None

                _mtime = await asyncio.to_thread(_probe_ok_cache_mtime)
                _cache_hit = False
                if _mtime is not None:
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
                    # R88 (round30): 符号集 = pool ETF + 持仓个股（600519 等 A 股 / AAPL 等
                    # US / 00700 等 HK）——个股不在 pool 内，不扩展则盘后 K 线空（§14.5）。
                    _warm_syms = await _kline_warmup_symbols(_syms[:30])
                    await asyncio.wait_for(market_data_hub.refresh_kline(_warm_syms), timeout=25)
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

    # R89 (round30): concept/industry 全量列表后台预拉（不占 warmup 30s 预算）。
    # 冷首呼 38.9s 根因 = akshare 全量拉取（round30 §11 实证）；就绪后异步预拉填充
    # sector_concept / sector_industry 缓存（ttl_key），首呼直接命中缓存。失败静默
    # （首呼回源兜底），与 _warmup_sector_cache 的「后台填充安全」同模式（F17/R44）。
    # 实现为模块级函数 `_warmup_sector_lists`（可单测），此处仅延迟调度。
    async def _delayed_sector_list_prefetch():
        try:
            await asyncio.sleep(30)
            await _warmup_sector_lists()
        except Exception:
            # round35 §11-T-①: 只捕 Exception——CancelledError 自然传播（任务已入
            # 容器，关停时必须可被取消），失败静默语义不变。
            logger.debug("[warmup] delayed sector list prefetch skipped (non-fatal)")

    from .core.background_tasks import spawn as _spawn_prefetch

    _spawn_prefetch(_delayed_sector_list_prefetch(), name="warmup-sector-lists")
    logger.info("[lifespan] 板块列表后台预拉已注册（延迟 30s，R89）")

    if _SKIP_WARMUP:
        logger.info("[lifespan] ETF_SURGE_SKIP_WARMUP=1, 跳过后台预热任务（快速启动模式）")
    else:
        _warmup_tasks.append(asyncio.create_task(_warmup_sequence_task()))

    # round35 §12.7-B 第一步（2026-08-23 决策）: APScheduler 定时推送链路已删除。
    # 调度器自 design-check-pipeline-redesign 危机期禁用一个月无人回切——请求驱动
    # （REST TTL 轮询 + warmup 一次预热）已被实证接受；恢复只会复活「空闲空转打源」
    # 的原始问题。行情缓存仍由 warmup 预热 + 15s TTL 惰性回源维护；portfolio 频道
    # 的 portfolio_changed 广播独立存活于 routers/portfolio.py，不受本决策影响。

    # Start health probe loop
    from .core.background_tasks import spawn as _spawn

    _spawn(health_loop(interval=120.0), name="loop-health")

    # round36 §8-B: 事件循环滞后看门狗——同步重段冻结循环时产出带栈告警转储
    # （known-env-issues §1.1「静默挂死」诊断成本收敛；shutdown_all 统一取消）
    from .core.loop_watchdog import start_loop_watchdog

    start_loop_watchdog(interval=1.0, threshold=5.0, dump_dir=_LOOP_WATCHDOG_DUMP_DIR)
    logger.info("[lifespan] 事件循环滞后看门狗已启动（threshold=5s）")

    # Start sector cache refresh loop (60s, Phase 2)
    async def _sector_refresh_loop():
        # 延迟 10s 首轮执行，让 ETF / 指数预热优先完成
        await asyncio.sleep(10)
        while True:
            try:
                await asyncio.wait_for(refresh_sector_cache(), timeout=20)
            except Exception:  # round35 §11-T-①: CancelledError 自然传播，取消才真正生效
                logger.warning("[lifespan] sector refresh cycle failed, will retry")
            await asyncio.sleep(60)
    _spawn(_sector_refresh_loop(), name="loop-sector")
    logger.info("板块缓存刷新循环已启动（60s）")

    # Start regime + sentiment refresh loop (120s, Phase 2.7.9)
    async def _regime_sentiment_refresh_loop():
        while True:
            try:
                from .services.market_data_hub import market_data_hub
                await asyncio.wait_for(market_data_hub.update_market_regime(), timeout=15)
                await asyncio.wait_for(market_data_hub.refresh_sentiment_cache(), timeout=15)
            except Exception:
                logger.warning("[lifespan] regime/sentiment refresh cycle failed, will retry")
            await asyncio.sleep(120)
    _spawn(_regime_sentiment_refresh_loop(), name="loop-regime-sentiment")
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
                    # Z18: 后台为重要新闻生成 AI 摘要（不阻塞刷新循环，失败静默）；
                    # round35 §11-T-①: 并入任务容器（强引用 + 完成自动摘除）。
                    _spawn(market_data_hub.enrich_news_summaries(), name="news-enrich")
                else:
                    logger.info("[lifespan] warmup in progress — skipping LLM news summaries (R5-1-1)")
            except Exception:
                logger.warning("[lifespan] news refresh cycle failed, will retry")
            await asyncio.sleep(120)
    _spawn(_news_refresh_loop(), name="loop-news")
    logger.info("资讯缓存刷新循环已启动（120s）")

    # round35 §19: 三层免费模型目录周期刷新（Zen+OpenRouter 池；LKG 兜底在模块内，
    # 刷新失败保旧池并 WARN，不造假数据）。目录空时 provider 层自动回退静态单候选。
    async def _model_catalog_refresh_loop():
        from .analysis.llm.model_catalog import model_catalog
        while True:
            try:
                await model_catalog.refresh(
                    (settings.opencode_zen_api_url or "").replace("/chat/completions", ""),
                    settings.opencode_zen_api_key,
                    (settings.openrouter_api_url or "").replace("/chat/completions", ""),
                    settings.openrouter_api_key,
                )
            except Exception:
                logger.warning("[lifespan] model catalog refresh failed, keep last-known-good")
            await asyncio.sleep(max(60, settings.llm_catalog_refresh_ttl))
    _spawn(_model_catalog_refresh_loop(), name="loop-model-catalog")
    logger.info("免费模型目录刷新循环已启动（%ds）", max(60, settings.llm_catalog_refresh_ttl))

    # round45 option C: NAV Redis 缓存预热循环 (lifespan 1618 任务治本)
    # 目的: 首次启动后 1h 内拉满 Redis 1618 候选; 二次启动 _inject_nav 全
    # Redis 命中 → 0 网络调用 → 事件循环 lag 峰值从 round45 量化 66.49s
    # 降至 < 1s. 设计:
    #   - 启动 60s 后首轮 (给 init_db / 预热 / 启动期 _inject_nav 先跑完)
    #   - 周期 1h (与 fetch_fund_nav 内部 _FUND_NAV_TTL 24h 错峰; 长短配合)
    #   - Semaphore(8) 并发限流 (与 _inject_nav 配额一致)
    #   - 调 get_fund_nav 走 Redis-first (本轮已改), 同步路径
    #   - Redis 不可用时降级 (cache_service._ensure_client 返 False)
    async def _nav_warmup_loop():
        from .services.market_data_hub import market_data_hub as _hub
        from .services.cache_service import redis_cache_sync
        import time as _time

        await asyncio.sleep(60)  # 延迟 60s 避开启动期 _inject_nav 抢资源
        _cycle = 0
        while True:
            _cycle += 1
            _t0 = _time.monotonic()
            try:
                if not redis_cache_sync.ping():
                    logger.debug("[lifespan/nav-warmup] Redis 不可用, 跳过本轮")
                else:
                    _pool = _hub.get_pool()
                    _syms: list[str] = []
                    for layer in _pool.values() if isinstance(_pool, dict) else []:
                        for it in layer:
                            s = it.get("symbol")
                            if s and s != "CASH":
                                _syms.append(s)
                    if not _syms:
                        logger.debug("[lifespan/nav-warmup] pool 空, 跳过本轮")
                    else:
                        # 调 get_fund_nav 走 Redis-first (本轮 §2.1 已改)
                        # 并发限流 Semaphore(8), 与 _inject_nav 配额一致
                        _sem = asyncio.Semaphore(8)
                        _ok = 0
                        _skip = 0
                        _err = 0

                        async def _warm_one(_s: str) -> None:
                            nonlocal _ok, _skip, _err
                            async with _sem:
                                try:
                                    # Redis 命中 → 立即返 (skip 走 fetch_fund_nav)
                                    _cached = redis_cache_sync.get(f"fund_nav:{_s}")
                                    if _cached is not None:
                                        _skip += 1
                                        return
                                    # miss → 调 get_fund_nav (内部 fetch + 回写)
                                    await asyncio.to_thread(
                                        _hub.get_fund_nav, _s,
                                    )
                                    _ok += 1
                                except Exception as _e:
                                    _err += 1
                                    logger.debug(
                                        "[lifespan/nav-warmup] %s failed: %s", _s, _e,
                                    )

                        await asyncio.gather(*[_warm_one(s) for s in _syms])
                        _dt = _time.monotonic() - _t0
                        logger.info(
                            "[lifespan/nav-warmup] cycle=%d n=%d ok=%d skip=%d err=%d dur=%.2fs",
                            _cycle, len(_syms), _ok, _skip, _err, _dt,
                        )
            except Exception as _e:
                logger.warning("[lifespan/nav-warmup] cycle failed: %s", _e)
            await asyncio.sleep(3600)  # 1h 周期
    _spawn(_nav_warmup_loop(), name="loop-nav-warmup")
    logger.info("NAV Redis 缓存预热循环已启动（1h 周期, 60s 延迟首轮）")

    # 崩溃恢复：扫描 report_quality="pending" 且创建 >5min 的记录，标记为 fallback
    try:
        async def _recover_stale_designs():
            from datetime import datetime, timedelta

            from sqlalchemy import select

            from .database import async_session
            from .models.portfolio_design import PortfolioDesign

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

            from .database import async_session
            from .models.task import TaskRecord

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
        from .database import async_session
        from .factors.factor_registry import registry
        from .factors.ic_tracker import ic_tracker

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
                    except Exception as _exc:
                        logger.debug("[ic_persistence] symbol_extra enrich skipped: %s", _exc)
                    await asyncio.wait_for(
                        _reg.compute(_syms, market_data=_kline, symbol_extra=_symbol_extra),
                        timeout=30,
                    )
            except Exception as exc:  # round35 §11-T-①: CancelledError 自然传播
                logger.debug("[ic_persistence] periodic compute skipped: %s", exc)
            await asyncio.sleep(120)

    _spawn(_ic_persistence_loop(), name="loop-ic-persistence")
    logger.info("IC 持久化循环已启动（120s）")

    # R55 (round27): 一次性 IC 历史回填（startup-once，非阻塞）。
    # 复用 K 线缓存时光回溯重放因子分，对每个历史交易日算截面 IC 批量落库，
    # 使 factor_ic_records.distinct trade_date 从 3 跳升至 ~239（≥60 →「可观察」，
    # 自然积累到 250 →「有效」，符合用户「接受等自然积累」决策）。
    # MIN_TRADING_DAYS 门槛不变（诚实，不谎报 valid）。
    # 仅当 K 线缓存就绪且尚未回填时执行；失败仅 WARNING，不影响启动。
    async def _backfill_ic_history_task():
        from .database import async_session
        from .factors.factor_registry import registry as _reg
        from .factors.ic_tracker import ic_tracker
        from .services.market_data_hub import market_data_hub as _hub

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
            # 防重复回填：已回填（接近可用上限）则跳过。
            # R102 (round33 §8.2): 跳过判据按 K 线实际深度（最长标的历史根数）动态定，
            # 余量 30 天——固定 ≥200 在「日线扩至 500、实际可达 ~490」下余量过大永不
            # 重跑（现有 245 恒跳过），在「池含大量新 ETF」下又可能误触发每启重跑。
            # R103 (round34): 深度只统计 K 线行（含 date 键）——场外净值序列
            # （019633 len=658 无 date 键）不得顶高阈值击穿 skip 判据。
            # 幂等：save_ic_batch_to_db 有 (factor_code, trade_date) 唯一约束 + upsert，
            # 同历日重填不重复不丢数据。
            kline_depth = _kline_depth_from_rows(rows)
            async with async_session() as db:
                _existing = await ic_tracker.count_distinct_trade_dates(db)
            if _ic_backfill_should_skip(_existing, kline_depth):
                logger.info(
                    "[ic_backfill] 已回填（%d 交易日 ≥ 可用 %d-30），跳过",
                    _existing, kline_depth,
                )
                return
            # 取池内 symbol（与持久化循环一致）——R58 延伸：磁盘 K 线缓存使 kline 门
            # 秒过，但启动时组合池尚未由设计数据预热填充（refresh() 60-90s），旧实现
            # 「组合池为空，跳过」恒跳过。改为轮询等待 pool 就绪（≤6×20s=120s）。
            _syms = await _wait_for_pool_symbols(_hub)
            if not _syms:
                logger.info("[ic_backfill] 组合池长时间为空（等待后放弃），跳过")
                return
            # 构造列式 K 线（时序升序）+ dates + OHLCV 五列（R108）
            kline: dict[str, dict] = _build_backfill_kline(rows, _syms)
            if len(kline) < 3:
                logger.info("[ic_backfill] K 线标的不足 3 只，跳过")
                return
            # symbol_extra（静态，不时光回溯；触网失败则空，因子分降级但可算）
            _symbol_extra: dict = {}
            try:
                _symbol_extra = await asyncio.wait_for(
                    _hub._enrich_symbol_extra(_syms, {}), timeout=15
                )
            except Exception as _e:
                # round35 §11-T-①: 本任务已入容器（task-ic-backfill），关停时
                # cancel 必须能穿透到此处——CancelledError 不再吞。
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
                    except Exception:
                        # round35 §11-T-①: 同上——CancelledError 自然传播，
                        # 关停时回填循环可被立即取消（不再逐迭代吞掉取消）。
                        continue
                    factor_scores_by_index[i] = {s: fs[s] for s in truncated}
            finally:
                _reg._last_ic_batch = _snap_batch
                _reg._last_computed_at = _snap_at
            # 批量落库
            async with async_session() as db:
                # R102 (round33 §8.2): 显式 max_days=n——默认 400 在 datalen=500 下
                # 只回填最旧 400 天、漏最近 ~100 天；传 n 让回填覆盖全部可用历史。
                cnt = await ic_tracker.backfill_ic_history(
                    db, kline, factor_scores_by_index, max_days=n
                )
            logger.info("[ic_backfill] 历史回填完成：%d 个交易日", cnt)
            # 回填后刷新 IC 序列缓存（供 /factors/active 加权聚合）
            try:
                async with async_session() as db:
                    await _reg.refresh_ic_series(db)
            except Exception as _e:
                logger.debug("[ic_backfill] refresh_ic_series failed: %s", _e)
        except Exception as exc:
            logger.warning("[ic_backfill] 历史回填失败（非致命）：%s", exc)

    _spawn(_backfill_ic_history_task(), name="task-ic-backfill")
    logger.info("IC 历史回填任务已启动（startup-once，非阻塞，R55）")

    # R5-1-5: 启动时从 DB 恢复 _last_ic_batch（IC 非请求驱动——重启后
    # /factors/active 不依赖任何请求即返回非空）。失败仅 WARNING，不阻塞启动。
    try:
        from .database import async_session as _ic_session
        from .factors.factor_registry import registry as _ic_registry

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

    # round35 §12.7-B: APScheduler 已删除（决策 B），无调度器需关停。
    # round35 §11-T-①: 先优雅关停全部在册后台任务（cancel + gather 收尾，
    # CancelledError 正常路径），再关存储——避免循环的 DB 写入被拦腰截断。
    from .core.background_tasks import shutdown_all as _shutdown_all

    _bg_errs = await _shutdown_all(timeout=10.0)
    for _bg_err in _bg_errs:
        logger.error("[lifespan] background task failed during shutdown: %r", _bg_err)
    # §12-P0-3 管线侧要求：shutdown 时 kline 缓存 flush（内存行落盘后存储再关）。
    try:
        from .services.market_data_hub import market_data_hub as _hub_shutdown

        _flush = getattr(_hub_shutdown, "flush_kline_cache", None)
        if callable(_flush):
            await asyncio.wait_for(
                _flush() if asyncio.iscoroutinefunction(_flush) else asyncio.to_thread(_flush),
                timeout=10,
            )
            logger.info("[lifespan] kline cache flushed on shutdown")
    except Exception as _e:
        logger.warning("[lifespan] kline cache flush skipped: %s", _e)
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

"""Admin 工具路由 — token 用量监控 / 数据源健康 / 事件记录等。"""

import asyncio
import logging
import time

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..core.source_registry import registry
from ..monitor.source_events import source_event_store
from ..monitor.token_usage import token_store

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

logger = logging.getLogger(__name__)


# ── Token Usage (existing) ──────────────────────────────────────


@router.get("/token-usage")
async def get_token_usage():
    """返回 DeepSeek token 使用统计（按 function 聚合 + 时间窗口）。"""
    return await token_store.summary()


@router.get("/token-usage/timeseries")
async def get_token_timeseries(
    granularity: str = Query("day", description="聚合粒度: hour / day / month"),
    days: int = Query(30, description="按天时: 最近 N 天", ge=1, le=365),
    months: int = Query(12, description="按月时: 最近 N 月", ge=1, le=60),
    hours: int = Query(48, description="按小时时: 最近 N 小时", ge=1, le=720),
):
    """返回 DeepSeek token 按小时/天/月的时间序列，供前端图表展示。"""
    if granularity == "month":
        ts = await token_store.timeseries(days=months, granularity="month")
        return {"granularity": "month", "series": ts["series"], "total": ts["total"]}
    if granularity == "hour":
        ts = await token_store.timeseries(granularity="hour", hours=hours)
        return {"granularity": "hour", "hours": hours, "series": ts["series"], "total": ts["total"]}
    ts = await token_store.timeseries(days=days, granularity="day")
    return {"granularity": "day", "days": days, "series": ts["series"], "total": ts["total"]}


@router.get("/token-usage/failures")
async def get_token_failures(
    limit: int = Query(50, description="返回最近 N 条失败记录", ge=1, le=200),
):
    """返回最近失败的 DeepSeek 调用记录（含错误信息）。"""
    return {"failures": await token_store.recent_failures(limit=limit)}


# ── Source Health Monitoring (new) ──────────────────────────────


@router.get("/sources/health")
async def get_sources_health():
    """返回所有注册数据源的当前健康状态概览。"""
    states = registry.get_states()
    import time
    now = time.time()
    result = []
    for name, h in states.items():
        # F17 R60: 过滤非数据源健康项（threadpool_* 探针）——线程池健康仍保留
        # 探测与告警，但不作为"数据源"展示在前端数据源页
        if name.startswith("threadpool_"):
            continue
        # Access health state via thread-safe snapshot
        with h._lock:
            result.append({
                "name": name,
                "available": now >= h._cool_until,
                "failures": h._failures,
                "cooldown_remaining": max(0.0, h._cool_until - now),
                "failure_threshold": h.failure_threshold,
                "cooldown_secs": h.cooldown,
            })
    return result


@router.get("/sources/events/timeline")
async def get_source_events_timeline(
    hours: float = Query(1, description="回溯小时数", ge=0.1, le=168),
):
    """返回数据源事件的时间线（按分钟聚合成功/失败计数）。"""
    return await source_event_store.timeline(hours=hours)


@router.get("/sources/events/failures")
async def get_source_events_failures(
    limit: int = Query(10, description="返回最近 N 条失败事件", ge=1, le=100),
):
    """返回最近的数据源失败事件。"""
    return await source_event_store.recent_failures(limit=limit)


@router.get("/sources/circuit-breakers")
async def get_source_circuit_breakers():
    """返回所有注册数据源的熔断器状态。"""
    return registry.circuit_breaker_status()


# ── Z05: SSL 连接池可观测 ───────────────────────────────────────


@router.get("/sources/connection-pool")
async def get_connection_pool():
    """Z05: 返回共享 HTTP 连接池统计（SSL 握手/复用次数）。"""
    from ..fetchers.global_markets_fetcher import get_connection_pool_stats

    stats = get_connection_pool_stats()
    return {
        "provider": "httpx.AsyncClient-shared-pool",
        **stats,
    }


# ── Thread Pool Monitoring ──────────────────────────────────────


@router.get("/thread-pool")
async def get_thread_pool():
    """返回主线程池和 akshare 专用线程池的实时统计。"""
    from ..core.async_utils import get_thread_pool_stats
    from ..services.market_data_hub import market_data_hub

    return {
        "main": get_thread_pool_stats(),
        "akshare": market_data_hub.get_akshare_pool_stats(),
        "warning_threshold_pct": 80,
    }


@router.get("/llm/health")
async def get_llm_health(
    timeout: float = Query(15.0, description="单供应商探测超时(秒)", ge=1.0, le=60.0),
    refresh: bool = Query(False, description="绕过 60s 缓存强制实时探测"),
):
    """F7: LLM 响应探针探测 —— 实时探测每个配置供应商的连通性。

    结果不进入业务链路，也不写入 token_store；探测失败返回结构化降级而非 500。
    供 verify_e2e F17 连通性测试与运维使用。

    round36 §9 (2026-08-25): 60s TTL 缓存 + refresh 旁路——供应商全死日单次
    探针持连 9-19s（真探针等超时），e2e/监控连环调用形成长持连请求簇，实测
    触发内核 accept backlog 瞬时溢出 → WinError 10061 连发（四路仪器取证：
    看门狗零转储/哨兵零卡顿/探针窗口零拒连，拒连全部落在无监控尾部）。
    缓存后重复调用毫秒级返回；与 get_factor_health 同款双重检查锁模式。
    """
    from ..analysis.llm import llm_health_check

    if not hasattr(get_llm_health, "_lock"):
        get_llm_health._lock = asyncio.Lock()
    _cache = getattr(get_llm_health, "_cache", None)
    if not refresh and _cache and time.time() - _cache["ts"] < 60:
        return _cache["data"]
    async with get_llm_health._lock:
        # 双重检查：等锁期间可能已被其他请求填充
        _cache2 = getattr(get_llm_health, "_cache", None)
        if not refresh and _cache2 and time.time() - _cache2["ts"] < 60:
            return _cache2["data"]
        result = await llm_health_check(timeout=timeout)
        get_llm_health._cache = {"ts": time.time(), "data": result}
        return result


@router.get("/factor-health")
async def get_factor_health():
    """#5: 因子计算健康检查 — 返回每个符号的非零因子比例。

    供 verify_e2e 和运维监控使用，不依赖 mock 环境。
    round10 P1-A: 加并发锁——多个请求同时缓存 miss 时只计算一次（10.9s 黑洞
    防抖），不阻塞各自返回（等待者直接等同一个计算）。
    """
    from ..factors.factor_registry import FactorRegistry
    if not hasattr(get_factor_health, "_lock"):
        get_factor_health._lock = asyncio.Lock()
    _cache = getattr(get_factor_health, "_cache", None)
    if _cache and time.time() - _cache["ts"] < 60:
        return _cache["data"]
    async with get_factor_health._lock:
        # 双重检查：等锁期间可能已被其他请求填充
        _cache2 = getattr(get_factor_health, "_cache", None)
        if _cache2 and time.time() - _cache2["ts"] < 60:
            return _cache2["data"]
        try:
            fr = FactorRegistry()
            symbols = ["510300", "518880", "511090"]
            result = await fr.compute(symbols)
            report = {}
            for sym in symbols:
                if sym in result:
                    scores = result[sym]
                    non_zero = sum(1 for v in scores.values() if isinstance(v, (int, float)) and abs(v) > 0.01)
                    total = len(scores)
                    report[sym] = {
                        "total": total, "live": non_zero,
                        "ratio": f"{non_zero}/{total}",
                        "healthy": non_zero >= max(10, total * 0.4),
                    }
            cached = {"status": "ok", "symbols": report}
            get_factor_health._cache = {"data": cached, "ts": time.time()}
            return cached
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ── Runtime Config Management (Phase 6.1.3) ─────────────────────


@router.get("/config")
async def get_config():
    """返回所有配置项的当前值（含 DB overrides + .env fallback）。"""
    from ..core.config_manager import config_manager
    return await config_manager.get_all()


@router.put("/config")
async def update_config(payload: dict[str, str]):
    """批量更新配置项，UPSERT 语义。

    请求体: {"DEEPSEEK_API_KEY": "sk-xxx", "TUSHARE_TOKEN": "...", ...}
    只处理 CONFIG_ITEMS 中定义的 key，忽略未知 key。
    """
    from ..core.config_manager import CONFIG_ITEMS, config_manager
    valid_keys = {item["key"] for item in CONFIG_ITEMS}
    results = {}
    for key, value in payload.items():
        if key not in valid_keys:
            results[key] = "skipped (unknown key)"
            continue
        await config_manager.set_override(key, str(value))
        results[key] = "updated"
    return {"results": results}


@router.delete("/config/{key}")
async def delete_config_override(key: str):
    """删除配置项的 DB override，恢复为 .env 值。"""
    from ..core.config_manager import CONFIG_ITEMS, config_manager
    valid_keys = {item["key"] for item in CONFIG_ITEMS}
    if key not in valid_keys:
        return {"status": "skipped", "reason": "unknown key"}
    await config_manager.delete_override(key)
    return {"status": "deleted", "key": key}


# ── System Metrics (7.2c) ────────────────────────────────────────


# P0-2 (round18 2.3/§7): metrics 热态 1.7s 恒定——拉 20 条完整 strategies_json +
# 每条 json.loads 遍历 + 2 次全表 count。修复：① 查询只取 strategies_json 列
# （不物化 design_text/market_snapshot_json 等大字段）；② 设计统计加内存 TTL 缓存
# 30s（对标 P0-8 designs_list 模式）。metrics 供 verify_e2e 使用，不能删。
_METRICS_CACHE: dict = {}


@router.get("/metrics")
async def get_system_metrics():
    """返回系统运行指标：池健康、设计成功率、并发失败计数等。

    供 verify_e2e 和运维监控使用，无需认证。
    """
    from sqlalchemy import func, select

    from ..database import async_session
    from ..models.portfolio_design import PortfolioDesign
    from ..services.market_data_hub import market_data_hub

    # P0-2: 30s TTL 缓存——DB 统计结果短时不变，热态命中缓存（负向：每次都重查 → FAIL）
    _now = time.monotonic()
    _cached = _METRICS_CACHE.get("metrics")
    if _cached and _now - _cached[0] < 30.0:
        return _cached[1]

    # 候选池健康
    pool = market_data_hub.get_pool()
    total_candidates = sum(len(v) for v in pool.values()) if pool else 0
    pool_healthy = total_candidates > 0

    # 连续刷新失败计数
    consecutive_failures = getattr(market_data_hub, '_consecutive_failures', -1)

    # 设计方案健康度
    design_success_rate = 0.0
    total_designs = 0
    recent_designs_with_etfs = 0
    recent_total = 0
    try:
        async with async_session() as db:
            # 近期设计成功率（P0-2: 只取 strategies_json 列，不物化其它大字段）
            result = await db.execute(
                select(PortfolioDesign.strategies_json)
                .order_by(PortfolioDesign.id.desc())
                .limit(20)
            )
            recent = result.scalars().all()
            recent_total = len(recent)
            for sjson in recent:
                import json
                strategies = json.loads(sjson) if sjson else []
                non_cash = 0
                for s in strategies:
                    etfs = s.get("etfs", [])
                    for a in etfs:
                        if a.get("symbol") != "CASH":
                            non_cash += 1
                if non_cash > 0:
                    recent_designs_with_etfs += 1

            # 全量成功率
            count_result = await db.execute(select(func.count()).select_from(PortfolioDesign))
            total_designs = count_result.scalar() or 0
            if total_designs > 0:
                success_count = await db.execute(
                    select(func.count()).select_from(PortfolioDesign).where(
                        PortfolioDesign.error_message.is_(None),
                        PortfolioDesign.status == "completed",
                    )
                )
                design_success_rate = (success_count.scalar() or 0) / total_designs
    except Exception as e:
        logger.warning("[admin/metrics] DB query failed: %s", e)

    result = {
        "pool": {
            "healthy": pool_healthy,
            "total_candidates": total_candidates,
            "consecutive_refresh_failures": consecutive_failures,
        },
        "designs": {
            "total": total_designs,
            "success_rate": round(design_success_rate, 4),
            "recent_20_with_etfs": recent_designs_with_etfs,
            "recent_20_total": recent_total,
        },
        "status": "ok" if (pool_healthy or total_designs > 0) else "degraded",
    }
    _METRICS_CACHE["metrics"] = (_now, result)
    return result


# ── LLM mark_excluded (round46 admin endpoint) ─────────────────────
# R143 熔断三件套的护栏 3 (排除表): 之前仅 in-memory _exclusions set, 重启清零.
# 落地路径:
# - GET /api/v1/admin/llm-excluded 列出 (provider, model) 列表
# - POST /api/v1/admin/llm-excluded  添加 (provider, model, reason?)
# - DELETE /api/v1/admin/llm-excluded/{provider}/{model}  取消排除
# 持久化: AppConfig 表 (与 config_manager.set_override 模式一致), key 格式
# `llm_excluded:<provider>:<model>`, value="1" (存在即排除).
# 启动期加载: main.py lifespan 调 model_catalog.load_excluded_from_keys().


from pydantic import BaseModel, Field


class LLMExcludedCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=64,
                          description="provider id, e.g. 'opencode_zen' / 'openrouter' / 'b_ai' / 'deepseek'")
    model: str = Field(..., min_length=1, max_length=128,
                       description="模型 id, e.g. 'deepseek-v4-flash-free'")
    reason: str | None = Field(default=None, max_length=256,
                               description="可选: 排除原因 (仅记录到日志)")


def _excluded_key(provider: str, model: str) -> str:
    return f"llm_excluded:{provider}:{model}"


@router.get("/llm-excluded")
async def list_llm_excluded():
    """列出所有 LLM 排除项 (跨重启持久化)."""
    from ..analysis.llm.model_catalog import model_catalog
    return {
        "items": model_catalog.list_excluded(),
        "total": len(model_catalog._exclusions),
    }


@router.post("/llm-excluded")
async def add_llm_excluded(body: LLMExcludedCreate):
    """添加 LLM 排除项 (持久化到 AppConfig 表 + 立即生效 in-memory).

    返回:
      - 201-like: {status: "added", provider, model}
      - 200-like: {status: "already_excluded", ...} 重复添加
      - 5xx: 持久化失败 (内存已加, 但 DB 失败 → 下次启动会丢)
    """
    from ..analysis.llm.model_catalog import model_catalog
    from ..core.config_manager import config_manager

    provider, model = body.provider.strip(), body.model.strip()
    if not provider or not model:
        return {"status": "error", "reason": "provider/model 不能为空"}, 400

    key = _excluded_key(provider, model)
    if f"{provider}:{model}" in model_catalog._exclusions:
        return {
            "status": "already_excluded",
            "provider": provider,
            "model": model,
        }

    # 1) 内存立即生效
    model_catalog.mark_excluded(provider, model)

    # 2) 持久化
    persisted = await config_manager.set_kv(key, "1")

    logger.info(
        "[admin/llm-excluded] +%s:%s reason=%r persisted=%s",
        provider, model, body.reason, persisted,
    )

    return {
        "status": "added",
        "provider": provider,
        "model": model,
        "persisted": persisted,
    }


@router.delete("/llm-excluded/{provider}/{model}")
async def remove_llm_excluded(provider: str, model: str):
    """取消 LLM 排除 (删除 DB key + in-memory set)."""
    from ..analysis.llm.model_catalog import model_catalog
    from ..core.config_manager import config_manager

    key = _excluded_key(provider, model)
    in_mem = model_catalog.unmark_excluded(provider, model)
    db_deleted = await config_manager.delete_kv(key)

    logger.info(
        "[admin/llm-excluded] -%s:%s in_mem=%s db_deleted=%s",
        provider, model, in_mem, db_deleted,
    )

    return {
        "status": "removed" if (in_mem or db_deleted) else "not_found",
        "provider": provider,
        "model": model,
        "in_mem_removed": in_mem,
        "db_deleted": db_deleted,
    }

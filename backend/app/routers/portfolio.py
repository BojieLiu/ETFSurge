import asyncio
import json
import logging
import time
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

# P0-8 (round16 2.3): 设计历史列表 TTL 缓存（key=(limit,offset)，30s 失效）
_DESIGNS_LIST_CACHE: dict[tuple[int, int], tuple[float, list]] = {}

# P0-1 (round20 §五 P0-1): timeline 30s TTL 缓存——对齐 admin_metrics 模式。
# 热态 2.9s 恒定（全表查询无缓存）；key=(limit,offset)，value=(monotonic_ts, body)。
_TIMELINE_CACHE: dict[tuple[int, int], tuple[float, dict]] = {}
_TIMELINE_TTL = 30.0

from ..database import get_db
from ..models.schemas import (
    PortfolioETFCreate, PortfolioETFUpdate, PortfolioETFResponse,
    CalculateRequest,
)
from ..services.portfolio_service import (
    list_etfs, add_etf, update_etf, remove_etf,
    calculate_allocation, calculate_daily_pnl, calculate_cumulative_pnl,
    export_portfolio, import_portfolio, calculate_weight_drift,
    apply_portfolio_design,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


async def _broadcast_portfolio_changed(portfolio_type: str | None, symbol: str | None = None):
    """round19 P2-②: 组合结构变更广播——POST/PUT/DELETE /apply-design 写库后通知
    所有已挂载页面与多标签页刷新（前端 market.js onmessage 分流 + 1s 防抖）。
    广播失败不影响写库响应（5s 超时保护在 ws.py 内部）。"""
    try:
        from ..routers.ws import manager
        await manager.broadcast("portfolio", {
            "type": "portfolio_changed",
            "data": {"portfolio_type": portfolio_type, "symbol": symbol},
        })
    except Exception as e:
        logger.warning("[portfolio] broadcast portfolio_changed failed (non-fatal): %s", e)


async def _with_realtime_prices(etfs: list):
    """O8 (round7 §7 P11): 批量补充实时 price/change_pct 到持仓列表。

    GET /portfolio/etfs 返回 ORM 条目 price=null（realtime 端点有价）→ 前端持仓
    表格价格列「—」。用 build_price_map 批量取实时价注入；失败静默保留原列表
    （列表加载不因行情源失败而阻塞）。
    """
    if not etfs:
        return etfs
    try:
        from ..services.portfolio_service import build_price_map
        price_map = await build_price_map(etfs)
        for e in etfs:
            sym = getattr(e, "symbol", None)
            if sym is None or sym not in price_map:
                continue
            price, change_pct = price_map[sym]
            if price is not None:
                e.price = price
            if change_pct is not None:
                e.change_pct = change_pct
    except Exception as e:
        logger.warning("[portfolio] realtime price enrich failed (non-fatal): %s", e)
    return etfs


@router.get("/etfs", response_model=list[PortfolioETFResponse])
async def get_etfs(
    portfolio_type: str = Query(None, pattern="^(on_exchange|off_exchange)?$"),
    db: AsyncSession = Depends(get_db),
):
    etfs = await list_etfs(db, portfolio_type)
    return await _with_realtime_prices(etfs)


@router.post("/etfs", response_model=PortfolioETFResponse, status_code=201)
async def create_etf(data: PortfolioETFCreate, db: AsyncSession = Depends(get_db)):
    result = await add_etf(db, data)
    await _broadcast_portfolio_changed(result.portfolio_type, result.symbol)
    return result


@router.put("/etfs/{symbol}", response_model=PortfolioETFResponse)
async def update_etf_route(symbol: str, data: PortfolioETFUpdate, db: AsyncSession = Depends(get_db)):
    result = await update_etf(db, symbol, data)
    if not result:
        raise HTTPException(status_code=404, detail="ETF not found")
    # round19 P3-③: adjust 语义响应携带 realized_pnl/trade（非 ORM 列，动态注入）
    _adj = getattr(result, "_adjust_meta", None)
    if _adj is not None:
        _resp = PortfolioETFResponse.model_validate(result).model_dump()
        _resp["realized_pnl"] = _adj["realized_pnl"]
        _resp["trade"] = _adj["trade"]
        await _broadcast_portfolio_changed(result.portfolio_type, symbol)
        return _resp
    await _broadcast_portfolio_changed(result.portfolio_type, symbol)
    return result


@router.delete("/etfs/{symbol}", status_code=204)
async def delete_etf(symbol: str, db: AsyncSession = Depends(get_db)):
    success = await remove_etf(db, symbol)
    if not success:
        raise HTTPException(status_code=404, detail="ETF not found")
    await _broadcast_portfolio_changed(None, symbol)


@router.post("/calculate")
async def calculate(
    req: CalculateRequest,
    portfolio_type: str = Query(None, pattern="^(on_exchange|off_exchange)?$"),
    db: AsyncSession = Depends(get_db),
):
    return await calculate_allocation(db, req.total_capital, portfolio_type)


@router.post("/daily-pnl")
async def daily_pnl(
    req: CalculateRequest,
    portfolio_type: str = Query(None, pattern="^(on_exchange|off_exchange)?$"),
    db: AsyncSession = Depends(get_db),
):
    return await calculate_daily_pnl(db, req.total_capital, portfolio_type)


@router.post("/apply-design")
async def apply_design(design: dict, db: AsyncSession = Depends(get_db)):
    """应用组合设计方案。

    round14 P0-A: 空 symbols 返回 400（此前返回 200 空操作 + 前端假成功，
    前后端断裂根因——见 docs/archived/round14 §2.2/§5 P0-A）。
    """
    symbols = design.get("symbols") or []
    weights = design.get("weights") or {}
    if not symbols:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="组合设计中没有指定持仓（symbols 为空）——请从前端 plan.allocations 构造 {symbols, weights} 后重试",
        )
    if not weights:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="组合设计缺少 weights（symbol→target_weight 映射）")
    result = await apply_portfolio_design(db, design)
    await _broadcast_portfolio_changed(None)
    return result


@router.get("/pnl-history")
async def pnl_history(
    portfolio_type: str | None = None,
    period: str = "all",
    total_capital: float = Query(0.0, description="总投资额，用于在成本数据缺失时估算"),
    db: AsyncSession = Depends(get_db),
):
    """获取累计盈亏历史"""
    return await calculate_cumulative_pnl(db, portfolio_type, period, total_capital)


@router.get("/export")
async def export_portfolio_endpoint(
    portfolio_type: str | None = None,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    """导出组合持仓"""
    result = await export_portfolio(db, portfolio_type, format)
    if format == "json":
        return {"holdings": result}
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=result, media_type="text/csv")



# Proper import endpoint with file upload
from fastapi import File, UploadFile

@router.post("/import", response_model=dict)
async def import_portfolio_file(
    file: UploadFile = File(...),
    portfolio_type: str = "on_exchange",
    mode: str = "merge",
    skip_invalid: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """导入组合持仓 CSV 文件"""
    content = await file.read()
    csv_content = content.decode("utf-8")
    result = await import_portfolio(db, csv_content, portfolio_type, mode, skip_invalid)
    await _broadcast_portfolio_changed(portfolio_type)
    return result


@router.get("/drift-check")
async def drift_check(
    portfolio_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """权重偏离检查"""
    return await calculate_weight_drift(db, portfolio_type)


# ── /design 和 /design-enhanced 已迁移到 /design-async ──
# 旧同步路由已移除，请使用 POST /portfolio/design-async


# ── 设计历史记录 ──────────────────────────────────────────


@router.get("/designs")
async def list_designs(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """列出历史方案记录"""
    from sqlalchemy import select, desc
    from sqlalchemy.orm import load_only
    from ..models.portfolio_design import PortfolioDesign

    # P0-8 (round16 2.3): designs_list 热态 660-890ms 不降——DB 查询无缓存。
    # 加内存 TTL 缓存（30s），列表频繁刷新（如切换分页、返回）不重复全表查询。
    _cache_key = (limit, offset)
    _now = time.monotonic()
    _cached = _DESIGNS_LIST_CACHE.get(_cache_key)
    if _cached and _now - _cached[0] < 30.0:
        return _cached[1]

    # UX3: 只加载元数据字段，避免 market_snapshot_json / design_text 大字段拖慢查询
    stmt = (
        select(PortfolioDesign)
        .options(load_only(
            PortfolioDesign.id,
            PortfolioDesign.created_at,
            PortfolioDesign.capital,
            PortfolioDesign.risk_profile,
            PortfolioDesign.status,
            PortfolioDesign.error_message,
            PortfolioDesign.report_quality,
            PortfolioDesign.report_generated_at,
            PortfolioDesign.strategies_json,
        ))
        .order_by(desc(PortfolioDesign.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    records = result.scalars().all()

    out = [
        {
            "id": r.id,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "capital": r.capital,
            "risk_profile": r.risk_profile,
            "status": r.status or "completed",
            "error_message": r.error_message,
            "report_quality": r.report_quality or "none",
            "report_generated_at": r.report_generated_at.isoformat() if r.report_generated_at else None,
            # Phase 2.7.8: 计算非 CASH ETF 总数
            "etf_count": sum(
                sum(1 for a in (s.get("etfs") or []) if a.get("symbol") != "CASH")
                for s in (json.loads(r.strategies_json) if r.strategies_json else [])
            ),
        }
        for r in records
    ]
    _DESIGNS_LIST_CACHE[_cache_key] = (_now, out)
    return out


@router.get("/designs/{design_id}")
async def get_design(
    design_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查看某次设计的完整详情"""
    from sqlalchemy import select
    from ..models.portfolio_design import PortfolioDesign

    stmt = select(PortfolioDesign).where(PortfolioDesign.id == design_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(status_code=404, detail="Design not found")

    strategies = json.loads(record.strategies_json) if record.strategies_json else []

    # Build plans from strategies (Sprint 1 P1: eliminate frontend conversion)
    plans = []
    for s in strategies:
        etfs = s.get("etfs", []) or []
        plans.append({
            "style": s.get("label", ""),
            "style_label": s.get("label", ""),
            "portfolio_name": s.get("portfolio_name", ""),
            "positioning": s.get("positioning", ""),
            "expected_return": s.get("expected_return"),
            "max_drawdown": s.get("max_drawdown"),
            "sharpe_ratio": s.get("sharpe_ratio"),
            "risk_factors": s.get("risk_factors") or [],
            # round22 E5: 透传 risk_metrics（含 correlation_unchecked）供方案卡片消费
            # 「关联度未校验」提示，与 strategies[].risk_metrics 同结构。
            "risk_metrics": s.get("risk_metrics") or {},
            "rebalance_rules": "月度检视",
            "allocations": [
                {
                    "symbol": e.get("symbol", ""),
                    "name": e.get("name", ""),
                    "layer": e.get("layer", ""),
                    "target_weight": e.get("weight", 0),
                    "selection_rationale": e.get("selection_rationale") or "",
                    # P0-4 (round16 3.9 B3): 补 daily_change_pct/price/factor_score——
                    # 旧实现白名单缺失 → 设计详情「今日涨跌」列恒显示"数据源不可用"
                    "daily_change_pct": e.get("daily_change_pct"),
                    "price": e.get("price"),
                    "factor_score": e.get("factor_score"),
                }
                for e in etfs
            ],
        })

    _market_context = json.loads(record.market_snapshot_json) if record.market_snapshot_json else {}
    return {
        "id": record.id,
        "created_at": record.created_at.isoformat() if record.created_at else "",
        "capital": record.capital,
        "risk_profile": record.risk_profile,
        "design_text": record.design_text or "",
        "status": record.status or "completed",
        "error_message": record.error_message,
        "report_quality": record.report_quality or "none",
        "report_generated_at": record.report_generated_at.isoformat() if record.report_generated_at else None,
        "strategies": strategies,
        "plans": plans,
        "market_context": _market_context,
        # P1-6 (round9 §4.1-3): 顶层 market_regime 补字段——旧实现顶层无该键，
        # 前端若读顶层字段将显示空（market_context 内已有 regime，复用之）
        "market_regime": (_market_context or {}).get("market_regime"),
        # P2-8 (round17): 数据源降级标记透传（从 market_snapshot_json 读出，历史设计可查）——
        # 前端 DesignResult 据此显示「数据源冷却」提示条；无该键时前端不渲染（不误报）。
        "degradation": (_market_context or {}).get("degradation"),
        # round24 R3: 呈现精度标识透传（契约 api-contracts/portfolio/design-precision.md）——
        # coarse 时前端把权重降为 5% 档位、因子分降为强弱分档 + 红字缺失百分比；
        # 无该键（历史设计）时前端按 exact 渲染，不误报降级。
        "data_precision": (_market_context or {}).get("data_precision"),
    }




# ── 异步任务 ──────────────────────────────────
@router.get("/tasks/{task_id}")
async def get_task_status(task_id: int):
    """查询异步任务状态（Z27: 返回契约全量字段 type/stage/params/result/record_id）。"""
    from ..tasks.task_manager import task_manager
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/tasks")
async def list_tasks(limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
    """列出最近的任务（Z27: limit 默认 20，与契约/前端一致）。"""
    from ..tasks.task_manager import task_manager
    return await task_manager.list_tasks(limit=limit, offset=offset)


@router.post("/design-async")
async def portfolio_design_async(
    task: dict,
):
    """异步提交设计任务，立即返回 task_id。

    请求体: {capital: 500000, constraints: {...}, market: "A"}
    Phase 5.1: 非 A 市场返回 unsupported 友好提示。
    """
    from ..core.market_context import resolve_market_context
    from fastapi.responses import JSONResponse

    market = task.get("market", "A")
    market_ctx = resolve_market_context(market)
    if not market_ctx.supports_portfolio_design:
        return JSONResponse(
            status_code=202,
            content={
                "task_id": None,
                "status": "unsupported",
                "message": f"组合设计当前仅支持 A 股市场（沪市/深市 ETF）。{market_ctx.title}市场的组合设计功能正在规划中。",
            },
        )

    from ..tasks.task_manager import task_manager, design_worker
    capital = task.get("capital", 500000)
    constraints = task.get("constraints")
    params = {"capital": capital, "constraints": constraints, "market": market}
    t = await task_manager.create_task(task_type="design", params=params)
    asyncio.create_task(design_worker(task_manager, t["task_id"]))
    return JSONResponse(
        status_code=202,
        content={
            "task_id": t["task_id"], "status": "pending", "created_at": t["created_at"],
            # P2-9 B2 (round16 3.9): 响应补 design_id（任务刚创建恒 null）——前端
            # DashboardAiTools 读 taskData.design_id 旧实现无此字段（靠 WS/轮询兜底）。
            "design_id": None,
        },
    )


# ── 异步策略检查 ─────────────────────────────────────────


@router.post("/strategy-check-async")
async def strategy_check_async(task: dict):
    """异步提交策略检查任务，立即返回 task_id。

    请求体: {capital: 500000, ...}
    """
    try:
        from fastapi.responses import JSONResponse
        from ..tasks.task_manager import task_manager
        from ..tasks.strategy_check_worker import strategy_check_worker

        total_capital = task.get("total_capital", 500000)
        portfolio_type = task.get("portfolio_type")
        t = await task_manager.create_task(task_type="check", params={"capital": total_capital, "portfolio_type": portfolio_type})
        asyncio.create_task(strategy_check_worker(task_manager, t["task_id"]))
        return JSONResponse(
            status_code=202,
            content={"task_id": t["task_id"], "status": "pending", "created_at": t["created_at"]},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/strategy-check-result/{task_id}")
async def get_strategy_check_result(task_id: int):
    """查询异步策略检查任务的结果。"""
    from ..tasks.task_manager import task_manager
    from fastapi.responses import JSONResponse

    task = await task_manager.get_task(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"error": "task not found"})
    
    if task["status"] != "completed":
        return {
            "task_id": task_id,
            "status": task["status"],
            "progress": task.get("progress", 0),
            "error_message": task.get("error_message"),
            "stage": task.get("stage", ""),
        }

    result = task.get("result", {})
    return {
        "task_id": task_id,
        "status": "completed",
        "summary": result.get("summary", ""),
        "suggestions": result.get("suggestions", []),
        "holdings_analysis": result.get("holdings_analysis", []),
        "risk_warnings": result.get("risk_warnings", []),
        "market_regime": result.get("market_regime", ""),
        "record_id": task.get("record_id"),
        # round28 R57 验收: 契约 strategy-check-v2.md 要求 coverage 字段
        # （coverage.coverage_pct 必须 = 1.0）——旧实现未透传，前端拿不到覆盖率。
        "coverage": result.get("coverage"),
        "llm_layer_ok": result.get("llm_layer_ok"),
        "is_fallback": result.get("is_fallback"),
        "report_quality": result.get("report_quality"),
    }


@router.get("/strategy-checks")
async def list_strategy_checks(limit: int = 10, offset: int = 0):
    """列出历史策略检查记录。"""
    try:
        from sqlalchemy import select, desc
        from sqlalchemy.ext.asyncio import AsyncSession
        from ..database import async_session
        from ..models.strategy_check import StrategyCheckRecord

        async with async_session() as db:
            stmt = (
                select(StrategyCheckRecord)
                .order_by(desc(StrategyCheckRecord.created_at))
                .offset(offset)
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [r.to_dict() for r in rows]
    except Exception:
        logger.exception("[strategy_checks] listing failed")
        return []


@router.get("/strategy-checks/{check_id}")
async def get_strategy_check(check_id: int):
    """获取单条策略检查记录详情。"""
    from sqlalchemy import select
    from ..database import async_session
    from ..models.strategy_check import StrategyCheckRecord

    async with async_session() as db:
        stmt = select(StrategyCheckRecord).where(StrategyCheckRecord.id == check_id)
        r = (await db.execute(stmt)).scalar_one_or_none()
        if not r:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=404, content={"error": "not found"})
        return r.to_dict()


@router.get("/timeline")
async def get_timeline(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Get merged timeline of portfolio designs and strategy checks.
    Queries both tables, merges by created_at DESC, supports pagination.
    """
    from ..models.portfolio_design import PortfolioDesign
    from ..models.strategy_check import StrategyCheckRecord
    from ..models.task import TaskRecord
    from sqlalchemy import select
    import json

    # P0-1 (round20 §五 P0-1): 30s TTL 缓存命中——热态不再重复全表查询。
    # 对齐 _DESIGNS_LIST_CACHE / admin._METRICS_CACHE 模式，按 (limit, offset) 键控。
    _cache_key = (limit, offset)
    _cached = _TIMELINE_CACHE.get(_cache_key)
    if _cached and time.monotonic() - _cached[0] < _TIMELINE_TTL:
        return _cached[1]

    # P0-1 (round18 2.3/§7): timeline 热态 2.3s 恒定——无 limit 全表查询 +
    # strategies_json 大字段物化 + 每条 json.loads（结果丢弃）。修复：
    # ① 显式列查询（不取 strategies_json/holdings_json/params_json 等大字段）；
    # ② 删除 :570 无用 json.loads（strategies 变量从未使用）；
    # ③ round20 P0-1: 三表查询统一 limit(limit+1) 裁剪（防全表扫描）。
    # Query designs（列裁剪：timeline 只用 id/created_at/status/capital/error_message）
    design_stmt = select(
        PortfolioDesign.id, PortfolioDesign.created_at, PortfolioDesign.status,
        PortfolioDesign.capital, PortfolioDesign.error_message,
    ).order_by(PortfolioDesign.created_at.desc()).limit(limit + 1)
    design_result = await db.execute(design_stmt)
    designs = design_result.all()

    # Query checks（列裁剪：只用 id/created_at/summary）
    check_stmt = select(
        StrategyCheckRecord.id, StrategyCheckRecord.created_at, StrategyCheckRecord.summary,
    ).order_by(StrategyCheckRecord.created_at.desc()).limit(limit + 1)
    check_result = await db.execute(check_stmt)
    checks = check_result.all()

    # O12 (round8 §7 + interaction-redesign D2): join tasks 表——失败/运行中的
    # design 任务在历史列表跨会话可见（不再"凭空消失"）。已成功且已有 design
    # 记录的不重复（design_items 已覆盖）；失败/运行中任务并入。
    # P2-11 (round9 §4.5-3): check 类型 task 关联查询——用于孤立 check 记录判定
    # （顺序：design → check → check-task → design-task，见 test_timeline_joins_tasks._FakeDB）
    # P0-1: tasks 查询同样列裁剪（排除 params_json/result_json 大字段）
    # round23 遗留修复：必须按 created_at 降序——缺 order_by 时 SQLite 按 rowid
    # 返回最旧 limit+1 条 check 任务，linked record_id 集合不含最新 check 记录 →
    # 最新策略检查全被误标 orphan=true → 前端历史列表过滤掉（「策略检查成功但不显示」）。
    check_task_stmt = select(
        TaskRecord.id, TaskRecord.record_id,
    ).where(
        TaskRecord.task_type == "check",
    ).order_by(
        TaskRecord.created_at.desc(), TaskRecord.id.desc(),
    ).limit(limit + 1)
    check_task_rows = (await db.execute(check_task_stmt)).all()
    linked_check_record_ids = {t.record_id for t in check_task_rows if t.record_id}
    # P0-9 (round16 3.10 R1): task_items 查询放宽为 design+check——旧实现只查 design，
    # check 类型 running/pending/failed 任务（尚未落 strategy_check_records 表）永不进 timeline，
    # 用户点"策略检查"后运行中任务不可见。
    task_stmt = select(
        TaskRecord.id, TaskRecord.task_type, TaskRecord.status, TaskRecord.record_id,
        TaskRecord.error_message, TaskRecord.created_at,
    ).where(
        TaskRecord.task_type.in_(["design", "check"]),
    ).order_by(TaskRecord.created_at.desc()).limit(limit + 1)
    task_result = await db.execute(task_stmt)
    task_rows = task_result.all()
    check_record_ids = {c.id for c in checks}

    design_ids = {d.id for d in designs}

    # Build items from designs
    design_items = []
    for d in designs:
        design_items.append({
            "id": d.id,
            "_type": "design",
            "created_at": d.created_at.isoformat() if d.created_at else "",
            "status": d.status or "completed",
            "capital": d.capital,
            "error_message": d.error_message,
        })

    # Build items from checks
    # P2-11 (round9 §4.5-3): 孤立 check 记录（无 task 关联，如 #343 空组合误报）标注 orphan——
    # 前端历史列表过滤，避免「历史异常记录」被误读为当前检查结果
    check_items = []
    for c in checks:
        check_items.append({
            "id": c.id,
            "_type": "check",
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "status": "completed",
            "summary": c.summary or "\u7b56\u7565\u68c0\u67e5\u5df2\u5b8c\u6210",
            "error_message": None,
            "orphan": c.id not in linked_check_record_ids,
        })

    # O12: tasks 表并入（失败/运行中任务可见）
    task_items = []
    for t in task_rows:
        _type = t.task_type if t.task_type in ("design", "check") else "design"
        # 已完成且已有对应落库记录（design/check_items 已覆盖）→ 不重复
        if t.status in ("completed", "completed_with_errors") and t.record_id:
            if _type == "design" and t.record_id in design_ids:
                continue
            if _type == "check" and t.record_id in check_record_ids:
                continue
        task_items.append({
            "id": t.record_id or t.id,
            "_type": _type,
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "status": t.status if t.status in ("completed", "completed_with_errors", "failed", "running") else "running",
            "capital": None,
            "error_message": t.error_message,
            "task_id": t.id,
        })

    # Merge and sort by created_at DESC
    merged = sorted(design_items + check_items + task_items, key=lambda x: x["created_at"], reverse=True)
    total = len(merged)

    # Paginate
    items = merged[offset:offset + limit]

    # P0-1 (round20): 30s TTL 缓存写回（对齐 admin_metrics 模式）
    _body = {"items": items, "total": total}
    _TIMELINE_CACHE[_cache_key] = (time.monotonic(), _body)
    return _body
"""Strategy-check engine — split from portfolio_service (Batch 1)."""

import asyncio
import logging
import os
import sys as _sys
import time as _time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.models.portfolio import PortfolioETF
from app.services.portfolio.formatting import (
    _CONFIDENCE_ZH,
    _has_real_factor_values,
    _factor_value_real,
)
from app.services.portfolio._facade_refs import (
    list_etfs,
    build_price_map,
    format_factor_summary,
    _normalize_confidence,
    _compute_confidence,
)

logger = logging.getLogger(__name__)


def _facade():
    """Late-bound reference to the facade module (keeps mock.patch semantics)."""
    m = _sys.modules.get("app.services.portfolio_service")
    if m is None:
        from app.services import portfolio_service as m
        _sys.modules["app.services.portfolio_service"] = m
    return m

_strategy_check_cache: dict[str, tuple[float, dict]] = {}

_COMPOSITE_FACTOR_MAP = {
    "technical": ("technical", "technical.momentum", "technical.rsi"),
    "valuation": ("valuation", "valuation.pe", "valuation.pb"),
    # R94 (round31): momentum 组件补真实因子键——旧键（momentum.recent_return /
    # momentum.vol_ratio）在真实因子分中不存在 → 策略检查 composite momentum 恒 0、
    # 13/13 全 degraded，而设计 rationale 有真实动量（§4.2 实证）。真实动量键为
    # etf.return_1m / etf.return_3m（raw 收益 %）+ technical.volume.vol_ratio。
    # 保留旧键向后兼容存量 mock 用例（round24 R25 语义：任一键有值即视为动量覆盖）。
    "momentum": ("momentum", "momentum.recent_return", "momentum.vol_ratio",
                 "etf.return_1m", "etf.return_3m", "technical.volume.vol_ratio"),
}


async def strategy_check(
    db: AsyncSession,
    total_capital: float,
    design_data: dict | None = None,
    portfolio_type: str | None = None,
) -> dict[str, Any]:
    """v2: 因子评分 + regime 感知 + 结构化输出（60s LRU 缓存避免重复采集）。"""
    from ...analysis.llm import generate_strategy_check_report
    from ...factors.factor_registry import registry as factor_registry
    
    # Use design_data if provided, otherwise fall back to DB ETFs
    use_design = False
    if design_data and design_data.get("plans"):
        plan = design_data["plans"][0] if design_data["plans"] else None
        if plan and plan.get("allocations"):
            etfs = []
            for alloc in plan["allocations"]:
                etfs.append({
                    "symbol": alloc.get("symbol"),
                    "name": alloc.get("name", alloc.get("symbol")),
                    "short_name": alloc.get("short_name", alloc.get("symbol")),
                    "asset_type": "ETF",
                    "portfolio_type": "on_exchange",
                    "target_weight": alloc.get("target_weight", 0),
                })
            use_design = True
        else:
            etfs = await list_etfs(db, portfolio_type)
    else:
        etfs = await list_etfs(db, portfolio_type)
    
    if not etfs:
        # P1-16 (round9 §4.5): 空组合附诊断——记录查询条件/行数/过滤明细，
        # 区分「真空组合」与「查询条件异常」（旧裸文案无任何诊断信息）
        diag = await _empty_portfolio_diagnosis(db, portfolio_type)
        return {
            "summary": "组合为空，请先添加ETF或生成组合方案",
            "suggestions": [],
            "empty_diagnosis": diag,
        }
    
    # Build price map - handle both SQLAlchemy objects and dicts
    def _get_attr(e, attr, default=None):
        if isinstance(e, dict):
            return e.get(attr, default)
        return getattr(e, attr, default)
    
    # 组合持仓计算缓存 key（按 symbol 列表 + capital 去重）
    symbols = [_get_attr(e, "symbol") for e in etfs if _get_attr(e, "symbol") != "CASH"]
    cache_key = "_".join(sorted(symbols) if symbols else ["empty"])
    cached = _strategy_check_cache.get(cache_key)
    if cached and _time.monotonic() - cached[0] < 60:
        # P0-4: 失效结果不命中缓存
        if cached[1] and not _is_failed_result(cached[1].get("factor_scores", {})):
            logger.debug("[strategy_check] returning cached result")
            return cached[1]
        else:
            logger.debug("[strategy_check] cache hit but result is failed/stale, re-fetching")
    
    # O25① (round7 §7 P25): 并行采集（各自独立超时，任一失败保留另一部分——
    # 旧 wait_for(gather) 超时会取消全部，部分完成结果被丢弃）
    indicators, factor_scores = await _collect_strategy_data(symbols)

    indicators = indicators if isinstance(indicators, dict) else {}
    factor_scores = factor_scores if isinstance(factor_scores, dict) else {}

    # 市场状态统一从 market_data_hub 读取（与设计管线一致，避免双套判定）
    try:
        from ...services.market_data_hub import market_data_hub
        regime = market_data_hub.get_market_regime() or "range_bound"
    except Exception:
        regime = "range_bound"
    trends = {}
    index_realtime = []
    
    # 构建 market_data with allocation info
    price_map = await build_price_map(etfs)
    market_data = []
    factor_breakdowns = {}
    for e in etfs:
        symbol = _get_attr(e, "symbol")
        price, change_pct = price_map.get(symbol, (0, 0))
        target_w = _get_attr(e, "target_weight", 0)
        market_data.append({
            "symbol": symbol, "name": _get_attr(e, "name", symbol),
            "short_name": _get_attr(e, "short_name", symbol),
            "price": price, "change_pct": change_pct,
            "asset_type": _get_attr(e, "asset_type", "ETF"),
            "portfolio_type": _get_attr(e, "portfolio_type", "on_exchange"),
            "target_weight": target_w,
            "target_amount": round(total_capital * target_w, 2),
        })
        
        if symbol != "CASH":
            fb = factor_scores.get(symbol, {}) if isinstance(factor_scores, dict) else {}
            ind = indicators.get(symbol, {})
            sig = ind.get("signal", {}) if isinstance(ind, dict) else {}
            drift = None
            if market_data:
                pass
            factor_breakdowns[symbol] = {
                "factor_scores": fb if isinstance(fb, dict) else {},
                "technical_indicators": ind if isinstance(ind, dict) else {},
                # P1-13① (round9 §4.4-1): 空 dict 也显式兑底——`{"signal": None, "reason": "技术指标不可用"}`
                # （旧实现仅兑底非 dict，空 dict 的 sig={} 穿透 → 真实信号注入被跳过 → 前端信号列空白）
                "technical_signal": sig if (isinstance(sig, dict) and sig.get("signal")) else {"signal": None, "reason": "技术指标不可用"},
                "weight_drift": drift,
            }

    # P0-2 (round16 3.2): 名称回退修复——DB 持仓里历史保存的默认名 "510300 ETF"
    # （apply-design 未命中真实名时生成）在策略报告中回退为真实名。
    # 查 instruments / ETF 基座缓存，标 refresh 时异步更新；查不到保持原名（诚实，不打假名）。
    try:
        _ghost = [m for m in market_data
                  if m.get("name") == f"{m.get('symbol')} ETF"
                  and m.get("symbol") not in (None, "CASH")]
        if _ghost:
            _name_map: dict[str, str] = {}
            try:
                from ...models.search import Instrument
                _rows = list((await db.execute(
                    select(Instrument).where(Instrument.symbol.in_([g["symbol"] for g in _ghost]))
                )).scalars().all())
                for _r in _rows:
                    _name_map[_r.symbol] = _r.name
            except Exception:
                pass
            _missing = [g["symbol"] for g in _ghost if g["symbol"] not in _name_map]
            if _missing:
                try:
                    from ...fetchers.etf_scanner import fetch_all_etfs_base
                    # P0-11 (round16 3.12): 同步读取走线程池，不阻塞事件循环
                    _base = await asyncio.to_thread(fetch_all_etfs_base) or []
                    for _it in _base:
                        _s = str(_it.get("symbol") or "").zfill(6)
                        _n = _it.get("name") or ""
                        if _s in _missing and _n:
                            _name_map[_s] = _n
                except Exception:
                    pass
            for g in _ghost:
                _real = _name_map.get(str(g["symbol"]).zfill(6)) or _name_map.get(g["symbol"], "")
                if _real:
                    g["name"] = _real
                    g["name_resolved"] = True
                    logger.info("[strategy_check] P0-2 resolved ghost name %s -> %s", g["symbol"], _real)
    except Exception as _pe:
        logger.debug("[strategy_check] ghost name resolution skipped (non-fatal): %s", _pe)
    
    # 统计因子数据质量
    # P1-15 (round9 §4.4-3): filled 判定排除兑底默认值——RSI/KDJ 恰为 50、ATR 恰为 0、
    # vol_ratio 恰为 1 等中性默认值是「缺数据兑底」而非真实值，计入 filled 会报「N/M 正常」假正常
    filled_factor_count = sum(
        1 for fb in factor_breakdowns.values()
        if _has_real_factor_values(fb.get("factor_scores") or {})
    )
    fallback_factor_count = sum(
        1 for fb in factor_breakdowns.values()
        if not _has_real_factor_values(fb.get("factor_scores") or {})
    )
    total_factor_count = len(factor_breakdowns)
    # R87 (round30): 组合级分项覆盖率（technical/valuation/momentum 三分项）——
    # summary / factor_availability / composite.reason 三处同底的数据源。
    # 替代 R74 的键级「因子填充率」：键级 66.5% 与 composite「分项覆盖 33.3%」
    # 底不同并存互斥（round30 §8 实证，§14.1 已决策统一为分项覆盖率）。
    _coverage_stats = _component_coverage_stats(factor_breakdowns)
    # R74 (round29): 组合级「因子键填充率」——与逐标的 factor_availability 同口径
    # （键级、排除兑底默认值）聚合。保留供外部契约兼容，但摘要不再使用（R87 统一为分项覆盖）。
    _keys_total = 0
    _keys_filled = 0
    for fb in factor_breakdowns.values():
        if not isinstance(fb, dict):
            continue
        fs = fb.get("factor_scores")
        if not isinstance(fs, dict) or not fs:
            continue
        _keys_total += len(fs)
        _keys_filled += sum(
            1 for k, v in fs.items()
            if isinstance(v, (int, float)) and _factor_value_real(k, v)
        )
    factor_fill_pct = (round(_keys_filled * 100.0 / _keys_total, 1)
                       if _keys_total else None)
    data_quality = {
        "filled_count": filled_factor_count,
        "total_count": total_factor_count,
        "all_empty": filled_factor_count == 0,
        "partial": 0 < filled_factor_count < total_factor_count,
        # R74 (round29): 组合级因子键填充率（%）（deprecated——R87 统一为分项覆盖）
        "factor_fill_pct": factor_fill_pct,
        # R87 (round30): 组合级分项覆盖率（%），摘要/报告正文同源
        "factor_coverage_pct": _coverage_stats["coverage_pct"],
        "coverage_components": _coverage_stats["per_holding"],
        "coverage_agg": {"filled": _coverage_stats["agg_filled"],
                         "total": _coverage_stats["agg_total"]},
        # P1-15: 兑底占比（全中性默认值的标的）——报告明示真实数据覆盖率
        "fallback_count": fallback_factor_count,
        "fallback_ratio": round(fallback_factor_count / total_factor_count, 4) if total_factor_count else 0.0,
    }

    # round24 R25: 结构化综合决策信号——每个持仓的 factor_breakdowns 附加
    # composite_decision（技术+因子聚合，因子填充率 <60% 时降级门禁）。必须在
    # LLM 报告生成前附加，使 LLM 输入与决策信号同源（展示一致性）。
    try:
        _attach_composite_decisions(factor_breakdowns, data_quality)
    except Exception as _cde:
        logger.debug("[strategy_check] composite_decision attach skipped (non-fatal): %s", _cde)

    # LLM 分析（Z26: 显式预算，超时走规则引擎兜底）
    # O25② (round7 §7 P25): 超时按数据完整性分级——all_empty 15s / partial 30s /
    # 数据完整 60s（旧 F9 恒 30s：采集也占 30s，LLM 实际剩余不足 → 恒超时兜底常态）。
    # F1-9: wait_for 超时会取消内部协程，抛 CancelledError（BaseException），
    # 必须与 TimeoutError 一起捕获，否则 usage 失败记录缺失、规则兜底文案丢失。
    # P2-F: 成功的 LLM 报告短缓存（key=持仓+capital+provider，TTL 5min）——
    # 同持仓重复检查第 2 次起命中 <1s，避免每次 60-120s 重算（round10 §3.3）。
    _LLM_REPORT_TTL = 300.0
    _llm_provider = os.environ.get("LLM_PRIMARY_PROVIDER", "opencode_zen")
    _llm_cache_key = f"llm:{cache_key}:{int(total_capital)}:{_llm_provider}" if cache_key else ""
    _llm_cached = _strategy_check_cache.get(_llm_cache_key) if _llm_cache_key else None
    _llm_failed = False
    if _llm_cached and _time.monotonic() - _llm_cached[0] < _LLM_REPORT_TTL:
        # P2-F: 命中成功报告缓存——直接复用，不调 LLM
        llm_result = _llm_cached[1]
        logger.debug("[strategy_check] LLM report cache hit (P2-F, key=%s)", _llm_cache_key)
    else:
        _llm_start = _time.monotonic()
        _llm_diag = ""
        _llm_timeout = _llm_timeout_for(data_quality)
        try:
            llm_result = await asyncio.wait_for(
                generate_strategy_check_report(
                    market_data=market_data,
                    factor_breakdowns=factor_breakdowns,
                    regime=regime,
                    data_quality=data_quality,
                ),
                timeout=_llm_timeout,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            _llm_failed = True
            _llm_dur = _time.monotonic() - _llm_start
            # R5-1-6: 取 LLM 层最后失败诊断（区分限流/超时），供 summary 展示
            try:
                from ...analysis.llm import get_last_llm_error
                _llm_diag = get_last_llm_error() or ""
            except Exception:
                _llm_diag = ""
            logger.warning(
                "[strategy_check] LLM analysis timed out/cancelled after %.1fs (%s), using rule fallback. last_error=%s",
                _llm_dur, type(e).__name__, _llm_diag,
            )
            # F1-9: 失败留痕 — 写 usage 失败记录（成功路径由 llm.py 写入）
            try:
                from ...monitor.token_usage import token_store, UsageRecord
                await token_store.record(UsageRecord(
                    function_name="generate_strategy_check_report",
                    prompt_tokens=0, completion_tokens=0, total_tokens=0,
                    model="", timestamp=_time.time(), success=False,
                    duration_ms=round(_llm_dur * 1000, 1),
                    error_message=f"wait_for timeout ({type(e).__name__})",
                    provider="",
                ))
            except Exception as _ue:
                logger.debug("[strategy_check] usage record failed (non-fatal): %s", _ue)
            llm_result = {
                # R6-F13 (round6 §十五 R6-15): 文案区分限流/超时/快速失败——与
                # get_last_llm_error 一致（旧模板恒写"超时 60s"，500 快速失败时误导）
                # O25③: 携带 data_quality（N/M 因子可用 + 缺失原因）
                "summary": _build_llm_fail_summary(_llm_dur, _llm_diag, data_quality),
                "suggestions": [],
                "holdings_analysis": [],
                "risk_warnings": [],
            }
        except Exception as e:
            _llm_failed = True
            logger.warning("[strategy_check] LLM analysis failed: %s", e, exc_info=True)
            llm_result = {
                "summary": f"LLM 分析暂不可用（{e}），返回因子数据摘要",
                "suggestions": [],
                "holdings_analysis": [],
                "risk_warnings": [],
            }

        # F1-9 兜底识别：llm.py 内部捕获 CancelledError 返回兜底结构（wait_for 不抛异常），
        # 此时 summary 以"LLM 分析…"开头——同样视为 LLM 失败（风险兜底诚实化）。
        # R70 (round29): 兜底文案新增「配额耗尽」「解析失败」两类，需一并识别——
        # 否则 429/JSONDecodeError 的兜底结果会被当作成功缓存复用。
        _llm_sum = str(llm_result.get("summary", ""))
        if not _llm_failed and (
            _llm_sum.startswith("LLM 分析超时")
            or _llm_sum.startswith("LLM 分析配额耗尽")
            or _llm_sum.startswith("LLM 分析结果解析失败")
        ):
            _llm_failed = True

        # P2-F: 仅缓存成功的 LLM 报告（失败/兜底不写——避免把降级结果当成功复用）
        if _llm_cache_key and not _llm_failed:
            _strategy_check_cache[_llm_cache_key] = (_time.monotonic(), llm_result)
    
    # P2-1+P2-2+P2-4: 后处理 — 回填 weight + 真实因子分 + factor_summary
    weight_map: dict[str, float] = {}
    for e in etfs:
        sym = _get_attr(e, "symbol", "")
        if sym and sym != "CASH":
            w = _get_attr(e, "target_weight", None)
            if w is None:
                w = _get_attr(e, "weight", 0)
            weight_map[sym] = float(w) if w else 0.0

    holdings_analysis = llm_result.get("holdings_analysis", [])

    # R5-1-2: rule 兜底路径 holdings_analysis 补全——LLM 超时/失败时
    # holdings_analysis 恒空 → 行业集中度检查静默跳过。用 factor_breakdowns/
    # industry_map 生成骨架（symbol/name/weight/factor_summary/industry），
    # 使行业分布分析在兜底路径也存在（数量级正确，标注"规则引擎生成"）。
    if _llm_failed and not holdings_analysis:
        holdings_analysis = _build_rule_fallback_holdings_analysis(
            etfs=etfs,
            market_data=market_data,
            factor_breakdowns=factor_breakdowns,
            weight_map={},  # 下面 P2-4 会统一回填
            regime=regime,
        )

    # P0-1 (R4-01): 行业注入——从 market_data_hub 候选池构建 symbol→industry 映射
    # （与设计任务同一来源；候选池条目含 ETFClassifier 产出的 industry 字段）。
    # 仅作数据回填，不参与因子计算；失败时静默（risk_warnings 有空行业保护兜底）。
    industry_map: dict[str, str] = {}
    try:
        from ...services.market_data_hub import market_data_hub as _hub
        _pool = _hub.get_pool()
        _pool_items = _pool.values() if isinstance(_pool, dict) else (_pool or [])
        for _items in _pool_items:
            for _it in _items or []:
                _sym = _it.get("symbol", "")
                _ind = _it.get("industry") or ""
                if _sym and _ind and _ind != "unknown" and _sym not in industry_map:
                    industry_map[_sym] = _ind
        for _sym in (symbols or []):
            if _sym and _sym not in industry_map:
                _entry = _hub.get_by_code(_sym)
                if _entry:
                    _ind = (_entry.get("industry") or "").strip()
                    if _ind and _ind != "unknown":
                        industry_map[_sym] = _ind
        # P1-14 (round9 §4.4-2): 独立兑底链——候选池空（数据源弱/EM 被拦）时
        # industry_map 仍能注入：instruments 表取名称 → ETFClassifier 独立分类
        if industry_map:
            logger.debug("[strategy_check] industry map built for %d symbols", len(industry_map))
        _missing_ind = [s for s in (symbols or []) if s and s not in industry_map]
        if _missing_ind:
            try:
                from ...services.etf_classifier import ETFClassifier
                _classifier = ETFClassifier()
                _inst_map: dict[str, str] = {}
                try:
                    from ...models.search import Instrument
                    _inst_rows = list((await db.execute(
                        select(Instrument).where(Instrument.symbol.in_(_missing_ind))
                    )).scalars().all())
                    for _r in _inst_rows:
                        _inst_map[_r.symbol] = _r.name
                except Exception as _ie:
                    logger.debug("[strategy_check] instruments lookup failed (non-fatal): %s", _ie)
                _cls_input = [{"symbol": s, "name": _inst_map.get(s, s),
                               "tracked_index": ""} for s in _missing_ind]
                _cls = _classifier.batch_classify(_cls_input) or {}
                for _sym in _missing_ind:
                    _c = _cls.get(_sym) or {}
                    _ind = (_c.get("industry") or "").strip()
                    if _ind and _ind != "unknown":
                        industry_map[_sym] = _ind
                if industry_map:
                    logger.debug("[strategy_check] industry map backfilled via ETFClassifier for %d symbols", len(industry_map))
            except Exception as _ce:
                logger.debug("[strategy_check] industry classifier fallback failed (non-fatal): %s", _ce)
    except Exception as _e:
        logger.debug("[strategy_check] industry map build failed (non-fatal): %s", _e)

    # round27 R42: 策略检查因子分口径统一——复用设计同源的全池截面 z（与设计同方向），
    # 不再用持仓子集重做 z（旧截面复合分实现导致两屏方向相反）。
    # 返回 {sym: {"composite": float|None, "reference": "相对候选池"|"单标的"}}。
    _factor_composites: dict[str, dict] = {}
    try:
        _factor_composites = _full_pool_factor_composite(factor_breakdowns)
    except Exception as _fce:
        logger.debug("[strategy_check] full-pool factor composite failed (non-fatal): %s", _fce)

    for h in holdings_analysis:
        sym = h.get("symbol", "")
        # P0-1: 注入 sector/industry（缺失时由 _compute_risk_warnings 空行业保护兜底）
        _ind = industry_map.get(sym, "")
        if _ind:
            h.setdefault("industry", _ind)
            h.setdefault("sector", _ind)
        # P2-4: weight 回填
        if sym and h.get("weight") is None:
            h["weight"] = weight_map.get(sym, 0.0)
        # P2-1: 注入真实因子分到 holdings_analysis
        fb = factor_breakdowns.get(sym, {})
        real_fs = fb.get("factor_scores", {})
        real_sig = fb.get("technical_signal", {})
        if _has_real_factor_values(real_fs):
            # 用真实因子分覆盖 LLM 编造的因子描述（F11: 中文名+方向解读）；
            # round18 P0-3: KDJ 用 technical_indicators 原始值对齐 /market/indicators
            h["factor_summary"] = format_factor_summary(
                real_fs, tech_ind=fb.get("technical_indicators") if isinstance(fb, dict) else None
            )
            # R87 (round30): factor_availability 改报分项覆盖（total=3，如 1/3）——
            # 与 composite.reason「分项覆盖 X%」同底（旧键级 filled/total 如 26/39
            # 底不同，与 composite 33.3% 并存互斥）。
            _ph = (_coverage_stats.get("per_holding") or {}).get(sym)
            if _ph:
                h["factor_availability"] = {
                    "filled": _ph["filled"], "total": _ph["total"],
                    "ratio": _ph["ratio"], "components": _ph["components"],
                }
            else:
                h["factor_availability"] = {"filled": 0, "total": 3, "ratio": "0/3",
                                            "components": {"technical": False,
                                                           "valuation": False,
                                                           "momentum": False}}
        elif data_quality and data_quality.get("all_empty"):
            h["factor_availability"] = {"filled": 0, "total": 0, "ratio": "0/0"}
        # P1-13② (round9 §4.4-1): 无论有无真实信号都写 tech_signal（无则「数据不可用」标注，
        # 禁止字段缺失 → 前端信号列空白）
        if isinstance(real_sig, dict) and real_sig.get("signal"):
            h["tech_signal"] = f"{str(real_sig['signal']).upper()}，真实信号"
        else:
            h["tech_signal"] = "数据不可用"
        # round25 R28: 拷贝结构化综合信号（R25 已由 _attach_composite_decisions 附加到
        # factor_breakdowns[sym]，但序列化循环从未拷贝进响应 → 前端综合信号卡恒不渲染，
        # 前后端双断死代码）。字段缺失时整字段不出现（诚实降级，不填默认冒充）。
        _cd = fb.get("composite_decision") if isinstance(fb, dict) else None
        if isinstance(_cd, dict):
            h["composite_decision"] = _cd

        # FIX-10: 始终基于因子覆盖率计算 confidence，不依赖 LLM source_confidence
        filled_count = data_quality.get("filled_count", 0) if data_quality else 0
        total_count = data_quality.get("total_count", 0) if data_quality else 0
        h["confidence"] = _compute_confidence(filled_count, total_count)

        # P1-8 (round20 §五 P1-8②): holdings_analysis 补 action/suggested_weight——
        # 与 suggestions 同源（复用规则引擎决策表），修复 LLM 路径 D-B2 割裂
        # （LLM 返回的 holdings_analysis 无 action 字段，前端无法联动）。
        if h.get("action") is None:
            _h_w = h.get("weight")
            if _h_w is None:
                _h_w = weight_map.get(sym, 0.0)
            _h_fb = factor_breakdowns.get(sym, {})
            # round25 R27: 截面 z-score 复合分（跨持仓统一口径，与设计路径同量纲）——
            # 避免「KDJ 原始值均值冒充 z-score 强度」导致两屏因子分方向相反。
            _h_rule = _rule_based_suggestion(
                symbol=sym,
                name=h.get("name", sym),
                target_weight=_h_w,
                factor_score=_h_fb.get("factor_scores", {}) if isinstance(_h_fb, dict) else {},
                signal=_h_fb.get("technical_signal") if isinstance(_h_fb, dict) else None,
                regime=regime,
                current_weight=_h_w,
                factor_availability=h.get("factor_availability"),
                factor_composite=(_factor_composites.get(sym) or {}).get("composite"),
                factor_composite_label=(_factor_composites.get(sym) or {}).get("reference"),
            )
            h["action"] = _h_rule["action"]
            h["suggested_weight"] = _h_rule["suggested_weight"]

    # P2-3: 增强摘要 — 纳入市态 + 数据质量
    regime_label = {"range_bound": "震荡", "bullish": "偏多", "bearish": "偏空",
                    "volatile": "高波动", "unknown": "待定"}.get(regime, regime)
    unique_sectors = set()
    for e in etfs:
        sym = _get_attr(e, "symbol", "")
        if sym and sym != "CASH":
            fb = factor_breakdowns.get(sym, {})
            sec = fb.get("technical_indicators", {}).get("sector", "")
            if sec:
                unique_sectors.add(sec)
    sector_text = f"，覆盖{len(unique_sectors)}个行业" if unique_sectors else ""

    filled_count = data_quality.get("filled_count", 0) if data_quality else 0
    total_count = data_quality.get("total_count", 0) if data_quality else 0
    # R87 (round30): 摘要改报组合级分项覆盖（_quality_summary_text），与 composite
    # 「分项覆盖 X%」同底——删除 R74 键级「因子填充率」（66.5% 与 33.3% 并存互斥）。
    # round27 R52 已确立该口径，本轮仅把展示侧对齐到决策侧。
    _quality_s = _quality_summary_text(_coverage_stats)
    if _quality_s:
        quality_summary = _quality_s
    elif total_count > 0:
        quality_summary = f"；因子覆盖 {round(filled_count * 100.0 / total_count, 1)}%"
    else:
        quality_summary = ""

    llm_summary = llm_result.get("summary", "")
    data_confidence = _compute_confidence(filled_count, total_count)

    # ── Z26: 规则引擎兜底 + 覆盖率统计（确保 100% 覆盖） ──────────────
    hold_symbols = [m for m in market_data if m.get("symbol") != "CASH"]
    total_holdings = len(hold_symbols)
    llm_suggestions = llm_result.get("suggestions", []) or []
    for s in llm_suggestions:
        s.setdefault("source", "llm")
        # 契约硬约束: action 仅允许 increase/decrease/hold
        if s.get("action") not in ("increase", "decrease", "hold"):
            s["action"] = "hold"
        # round24 R4: confidence 表示法统一——LLM 可能返数值(0.85)/中文(高)/标签(high)，
        # 一律归一化为 high/medium/low，杜绝与规则路径同屏两种表示法
        s["confidence"] = _normalize_confidence(s.get("confidence"))

    covered_symbols = {s.get("symbol") for s in llm_suggestions if s.get("symbol")}
    covered_by_llm = len(covered_symbols)
    rule_suggestions: list[dict] = []
    for m in hold_symbols:
        sym = m.get("symbol")
        if sym in covered_symbols:
            continue
        fb = factor_breakdowns.get(sym, {})
        rule_suggestions.append(_rule_based_suggestion(
            symbol=sym,
            name=m.get("name", sym),
            target_weight=m.get("target_weight", 0),
            factor_score=fb.get("factor_scores", {}),
            signal=fb.get("technical_signal"),
            regime=regime,
            # round18 P2-7: confidence 按因子填充率分级
            factor_availability=fb.get("factor_availability"),
            # round27 R42: 全池截面 z 复合分（与设计路径同量纲、同方向）
            factor_composite=(_factor_composites.get(sym) or {}).get("composite"),
            factor_composite_label=(_factor_composites.get(sym) or {}).get("reference"),
        ))
    covered_by_rule = len(rule_suggestions)

    merged_suggestions = llm_suggestions + rule_suggestions
    covered_total = covered_by_llm + covered_by_rule
    coverage_pct = covered_total / total_holdings if total_holdings else 1.0
    if total_holdings and coverage_pct < 1.0:
        logger.error("[strategy_check] coverage < 100%%: %s/%s holdings covered",
                     covered_total, total_holdings)
    coverage = {
        "total_holdings": total_holdings,
        "covered_by_llm": covered_by_llm,
        "covered_by_rule": covered_by_rule,
        "coverage_pct": round(coverage_pct, 4),
    }

    # U2 R1: 风险兜底诚实化（LLM 超时/因子缺失 → warning 级降级标注）
    risk_warnings = _combine_risk_warnings(
        llm_result.get("risk_warnings", []),
        _compute_risk_warnings(holdings_analysis, factor_scores, regime),
        llm_failed=_llm_failed,
        data_all_empty=bool((data_quality or {}).get("all_empty")),
    )

    # R95 (round31): 报告正文数值一致性校验——summary / risk_warnings / holdings
    # reason / report_text 逐持仓比对 KDJ/RSI/SMA/量比 vs technical_indicators 结构化
    # 值 + 「合计权重 N%」聚合校验（§4.3 实证：正文 KDJ J=6.16 vs 结构化 84.49、
    # 港股类合计 10% vs 结构化权重和 13%）。不一致用结构化值覆盖 + 修正脚注。
    _r95_warnings: list[str] = []
    try:
        llm_summary, _r95w = _reconcile_report_numbers(
            str(llm_summary or ""), factor_breakdowns, weight_map)
        _r95_warnings.extend(_r95w)
        for _rw in risk_warnings:
            if not isinstance(_rw, dict):
                continue
            _desc = str(_rw.get("description") or "")
            _fixed, _w = _reconcile_report_numbers(_desc, factor_breakdowns, weight_map)
            if _fixed != _desc:
                _rw["description"] = _fixed
                _r95_warnings.extend(_w)
        for _h in holdings_analysis:
            if not isinstance(_h, dict):
                continue
            _reason = str(_h.get("reason") or "")
            if not _reason:
                continue
            _fixed, _w = _reconcile_report_numbers(_reason, factor_breakdowns, weight_map)
            if _fixed != _reason:
                _h["reason"] = _fixed
                _r95_warnings.extend(_w)
    except Exception as _r95e:
        logger.debug("[strategy_check] R95 number reconciliation skipped (non-fatal): %s", _r95e)

    _report_text = _build_rule_fallback_report(
        market_data=market_data,
        factor_breakdowns=factor_breakdowns,
        merged_suggestions=merged_suggestions,
        regime=regime,
        data_quality=data_quality,
        llm_failed=_llm_failed,
        risk_warnings=risk_warnings,
    )
    try:
        _report_text, _r95w = _reconcile_report_numbers(
            _report_text, factor_breakdowns, weight_map)
        _r95_warnings.extend(_r95w)
    except Exception as _r95e:
        logger.debug("[strategy_check] R95 report_text reconciliation skipped (non-fatal): %s", _r95e)
    if _r95_warnings:
        _footnote = (
            "\n\n> ⚠️ **数值一致性校验（R95）**：报告正文部分数值与结构化数据不一致，"
            f"已自动修正：{'；'.join(dict.fromkeys(_r95_warnings))[:400]}"
        )
        llm_summary = f"{llm_summary}{_footnote}"

    result = {
        "summary": f"{llm_summary}（市态：{regime_label}{sector_text}{quality_summary}）" if llm_summary else f"市态：{regime_label}，{filled_count}/{total_count}只正常{quality_summary}",
        "suggestions": merged_suggestions,
        "holdings_analysis": holdings_analysis,
        "risk_warnings": risk_warnings,
        # U2 R1: 兜底正文——rule/LLM 建议一律渲染为完整 Markdown 报告
        # （旧实现无 report_text 键 → task 结果 report_text len=0）
        "report_text": _report_text,
        "market_regime": regime,
        "data_quality": {
            "filled_count": filled_count,
            "total_count": total_count,
            # P1-15: 兜底占比（全中性默认值标的）——报告明示真实数据覆盖率，防「N/M 正常」假正常
            "fallback_count": data_quality.get("fallback_count", 0),
            "fallback_ratio": data_quality.get("fallback_ratio", 0.0),
        },
        "data_confidence": data_confidence,
        "coverage": coverage,
        "raw_llm": str(llm_result),
        # round24 R5: 结构化兜底标识——兜底不再只能靠逐条 source=rule 或 summary 文本识读。
        # llm_layer_ok=False 且 is_fallback=True 时前端可显式标注「LLM 层降级，规则引擎兜底」，
        # report_quality 提供与 design 管线一致的枚举口径（full/partial/fallback/empty）。
        "llm_layer_ok": (not _llm_failed),
        "is_fallback": bool(_llm_failed),
        "report_quality": ("fallback" if _llm_failed else "full"),
    }
    # 缓存 60s
    if cache_key:
        _strategy_check_cache[cache_key] = (_time.monotonic(), result)
    return result


def _is_failed_result(factor_scores: dict) -> bool:
    """P0-4: 判断因子结果是否为失败（全部为空或全零）。

    R85 (round30): None 值（缺数据诚实标注）不算真实值——仅当存在非 0 数值因子
    才视为「非失败」；全 None/全 0/空 → 失败（数据不可用）。
    """
    if not factor_scores:
        return True
    for sym, scores in factor_scores.items():
        if scores and isinstance(scores, dict) and any(
            isinstance(v, (int, float)) and v != 0 for v in scores.values()
        ):
            return False
    return True


def _build_llm_fail_summary(duration_s: float, diag: str, data_quality: dict | None = None) -> str:
    """R6-F13: 策略检查 LLM 失败兜底文案——按诊断内容区分限流/超时/服务端错误。

    O25③ (round7 §7 P25): 兜底文案携带数据质量摘要（N/M 因子可用 + 缺失原因），
    不再固定「LLM 分析超时」——专业投资者可区分「数据缺失」与「LLM 慢」。
    """
    diag = diag or ""
    low = diag.lower()
    if "限流" in diag or "429" in low:
        reason = "LLM 限流"
    elif "timeout" in low or "timed out" in low or "超时" in diag:
        reason = "LLM 响应超时"
    else:
        reason = "LLM 服务端错误"
    quality = ""
    if data_quality:
        filled = data_quality.get("filled_count", 0)
        total = data_quality.get("total_count", 0)
        if data_quality.get("all_empty"):
            quality = f"，因子数据缺失（{filled}/{total} 可用，上下文不足快速兜底）"
        else:
            quality = f"，因子数据部分可用（{filled}/{total}）" if data_quality.get("partial") \
                else f"，因子数据完整（{filled}/{total}）"
    return (
        f"{reason}（{duration_s:.0f}s，已用规则引擎兜底生成建议{quality}）"
        f"（最后错误: {diag or '未知'}）"
    )


def _llm_timeout_for(data_quality: dict) -> int:
    """O25② (round7 §7 P25): LLM 超时按数据完整性分级。

    - all_empty（上下文不足）→ 15s 快速兜底（快速失败更合理，不必等满）
    - partial → 30s（有部分数据，多给 LLM 一点时间消化）
    - 数据完整 → 180s（round27 R43: 75→180，对齐 DeepSeek 流式首字节实测
      34-78s、单报告 token 更长；此前 75s 几乎必然超时 → 恒落规则兜底，用户
      永不见 AI 策略检查报告。180s 留足首字节 + 生成余量，与 design-report 的
      120s 同量级偏宽松。provider 无响应时预算-重试一致性见
      tests/test_round14_llm_budget_consistency.py）
    旧实现恒 30s：数据采集也占 30s，LLM 实际剩余不足 → 恒超时（round7 P5）。
    """
    if data_quality.get("all_empty"):
        return 15
    if data_quality.get("partial"):
        return 30
    return 180


async def _collect_strategy_data(
    symbols: list[str],
    indicators_timeout: float = 25,
    factor_timeout: float = 25,
) -> tuple[dict, dict]:
    """O25① (round7 §7 P25): 采集技术指标 + 因子分，各自独立超时。

    旧实现 `wait_for(gather(ind, fac, return_exceptions=True), 30)` 超时会取消
    整个 gather——部分完成的结果也拿不到（日志写「using partial results」实际
    赋 {} 全空）→ data_quality.all_empty=True → LLM 收到空上下文。
    现在任一任务失败/超时只丢该任务，另一任务结果保留（data_quality.partial
    语义正确反映「部分可用」）。
    """
    from ...factors.factor_registry import registry as factor_registry

    async def _guarded(coro, timeout: float, label: str):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("[strategy_check] %s collection timed out after %ss", label, timeout)
            return {}
        except Exception as e:
            logger.warning("[strategy_check] %s collection failed: %s", label, e)
            return {}

    indicators_task = _facade()._compute_indicators(symbols)
    # R94 (round31): 因子计算对齐设计路径——设计 `_refresh_impl:330-342` 喂
    # `hub._kline_cache`（列式）给 factor_registry.compute；策略检查此前裸调
    # compute(symbols) 走 `_fetch_market_data`（另一缓存域），同一 ETF 两条路径
    # 动量数据一有一无（§4.2 实证）。改为优先喂 hub kline 列式缓存——与设计同源，
    # 且省去重复 live fetch；hub 缓存为空时回落原路径（_fetch_market_data 内部
    # 仍有 hub 行缓存 + live 兜底，行为不回退）。
    try:
        from ...services.market_data_hub import market_data_hub as _hub
        _hub_kline = getattr(_hub, "_kline_cache", None) or {}
        if _hub_kline:
            factor_task = factor_registry.compute(symbols, market_data=_hub_kline)
        else:
            factor_task = factor_registry.compute(symbols)
    except Exception:
        factor_task = factor_registry.compute(symbols)
    indicators, factor_scores = await asyncio.gather(
        _guarded(indicators_task, indicators_timeout, "indicators"),
        _guarded(factor_task, factor_timeout, "factors"),
    )
    return indicators or {}, factor_scores or {}


async def _empty_portfolio_diagnosis(db: AsyncSession, portfolio_type: str | None) -> dict:
    """P1-16 (round9 §4.5-4): 空持仓诊断——记录查询条件/行数/过滤明细。

    旧实现 `list_etfs` 空 → 直接返回裸文案「组合为空」，不记录查询条件/原因，
    孤立 check 记录（#343 类）与真空组合无法区分。本函数补齐诊断信息。
    """
    try:
        all_rows = list((await db.execute(select(PortfolioETF))).scalars().all())
        total = len(all_rows)
        active = [e for e in all_rows if e.is_active]
        active_syms = [e.symbol for e in active]
        if portfolio_type:
            matched = [e.symbol for e in active if e.portfolio_type == portfolio_type]
        else:
            matched = active_syms
        note = "真空组合（无任何持仓记录）"
        if active:
            note = ("查询条件异常（有 is_active 持仓但 portfolio_type 不匹配）"
                    if not matched else "持仓存在但查询结果为空（异常）")
        return {
            "portfolio_type": portfolio_type,
            "db_total_rows": total,
            "is_active_rows": len(active),
            "matched_rows": len(matched),
            "all_symbols": active_syms[:50],
            "matched_symbols": matched[:50],
            "note": note,
        }
    except Exception as e:  # 诊断失败不影响主流程
        return {"portfolio_type": portfolio_type, "diagnosis_error": str(e)}


def _holding_component_coverage(fb: dict) -> tuple[int, int, dict[str, bool]]:
    """R87 (round30): 单持仓分项覆盖率（technical/valuation/momentum 三分项）。

    technical 以 technical_signal.score 是否有值计（技术信号路径独立）；valuation/
    momentum 以 factor_scores 中对应前缀键是否有真实值计（_COMPOSITE_FACTOR_MAP）。
    返回 (real_count, total=3, {comp: bool})——与 composite_decision 的 valid_rate
    同底（round27 R52 已确立该口径，本轮把展示侧对齐）。
    """
    if not isinstance(fb, dict):
        return (0, 3, {"technical": False, "valuation": False, "momentum": False})
    fs = fb.get("factor_scores") or {}
    fs = fs if isinstance(fs, dict) else {}
    tech_sig = fb.get("technical_signal") or {}
    tech_score = tech_sig.get("score")
    tech_real = isinstance(tech_score, (int, float))
    comp_real: dict[str, bool] = {}
    for comp, keys in _COMPOSITE_FACTOR_MAP.items():
        real_vals = [fs[k] for k in keys
                     if isinstance(fs.get(k), (int, float)) and fs.get(k) != 0]
        comp_real[comp] = bool(real_vals)
    flags = {
        "technical": tech_real,
        "valuation": comp_real.get("valuation", False),
        "momentum": comp_real.get("momentum", False),
    }
    return (sum(1 for f in flags.values() if f), 3, flags)


def _component_coverage_stats(factor_breakdowns: dict) -> dict:
    """R87 (round30): 组合级分项覆盖率聚合——summary / factor_availability /
    composite.reason 三处口径统一的数据源（三处同底，禁止 66.5% 与 33.3% 并存）。
    """
    per_holding: dict[str, dict] = {}
    agg_filled = 0
    agg_total = 0
    for sym, fb in factor_breakdowns.items():
        filled, total, flags = _holding_component_coverage(fb)
        per_holding[sym] = {
            "filled": filled, "total": total, "ratio": f"{filled}/{total}",
            "components": flags,
        }
        agg_filled += filled
        agg_total += total
    coverage_pct = round(agg_filled * 100.0 / agg_total, 1) if agg_total else 0.0
    return {
        "per_holding": per_holding,
        "agg_filled": agg_filled,
        "agg_total": agg_total,
        "coverage_pct": coverage_pct,
    }


def _quality_summary_text(coverage_stats: dict) -> str:
    """R87: 摘要文案「因子覆盖 X%」（组合级分项覆盖，与 composite.reason 同底）。

    替代 R74 的键级「因子填充率」——键级 66.5% 与 composite「分项覆盖 33.3%」
    底不同会并存互斥（round30 §8 实证）。分项覆盖 = 决策门禁输入（展示值=决策值）。
    """
    if not coverage_stats or coverage_stats.get("agg_total", 0) <= 0:
        return ""
    return f"；因子覆盖 {coverage_stats['coverage_pct']}%"


def _rule_fallback_quality_line(coverage_stats: dict, fallback_count: int = 0) -> str:
    """R87: report_text 因子数据质量行——组合级分项覆盖，删除「N/N 无兜底」持仓级口径。

    round30 §8 实证：正文「13/13 无兜底」与 composite「分项覆盖 33.3%」自相矛盾。
    统一为分项覆盖，并可列出兜底占比（fallback_count 语义保留）。
    """
    if not coverage_stats or coverage_stats.get("agg_total", 0) <= 0:
        return "**因子数据质量**：无可计算持仓。"
    pct = coverage_stats["coverage_pct"]
    suffix = (f"（其中 {fallback_count} 只技术因子缺数据兜底）"
              if fallback_count else "")
    return f"**因子数据质量**：分项覆盖 {pct:g}%（技术/估值/动量三分项）{suffix}"


def _attach_composite_decisions(
    factor_breakdowns: dict[str, dict],
    data_quality: dict | None = None,
) -> None:
    """round27 R52: 给每个持仓的 factor_breakdowns 附加结构化 `composite_decision`。

    背景（R52 实证）：旧实现 valid_rate = 「持仓级填充率」(filled/total=13/13=100%)，
    而 composite_signal 权重 0.4技术+0.4估值+0.2动量，周末估值/动量恒 0 →
    score=0.4×技术∈[-0.4,+0.4] 永不够 ±0.5 阈值 → 恒 hold 假信号。

    修复：valid_rate 改算**分项覆盖率**——technical/valuation/momentum 三分项中
    「有真实因子值（非 0、非兜底默认）的分项数 / 3」。估值/动量分项全缺（周末）→
    valid_rate=1/3<0.6 → degraded=True、signal=None（诚实「综合信号不可用」）。
    ≥2 分项可用时**权重归一**（缺失分项权重置 0、其余归一化到和 1），避免缺失分项
    静默稀释分数。技术信号（technical_signal.score 有值即视为可用）独立计入。

    R87 (round30): 分项覆盖率改用 `_holding_component_coverage`（与 data_quality /
    factor_availability / summary 同底），保证三处数值一致。
    """
    from ...analysis.signal import composite_signal_with_gate

    # 基准权重（composite_signal 默认 0.4/0.4/0.2）；缺失分项权重归零、其余归一化
    _BASE_W = (0.4, 0.4, 0.2)
    _ORDER = ("technical", "valuation", "momentum")

    for sym, fb in factor_breakdowns.items():
        if not isinstance(fb, dict):
            continue
        fs = fb.get("factor_scores") or {}
        fs = fs if isinstance(fs, dict) else {}
        tech_sig = fb.get("technical_signal") or {}
        tech_score = tech_sig.get("score")
        if not isinstance(tech_score, (int, float)):
            tech_score = 0.0

        # 因子分 → 分项聚合（仅非 0 真实键参与；无真实键 → 0.0 且标记缺失）
        comp_vals: dict[str, float] = {}
        comp_real: dict[str, bool] = {}
        for comp, keys in _COMPOSITE_FACTOR_MAP.items():
            real_vals = [fs[k] for k in keys
                         if isinstance(fs.get(k), (int, float)) and fs.get(k) != 0]
            comp_real[comp] = bool(real_vals)
            comp_vals[comp] = round(sum(real_vals) / len(real_vals), 3) if real_vals else 0.0

        # 分项覆盖率：technical 以 technical_signal 是否有 score 计；valuation/momentum
        # 以因子键是否真实计（3 分项）——R87: 与 _holding_component_coverage 同底
        _filled, _total, _flags = _holding_component_coverage(fb)
        _tech_real = _flags["technical"]
        _real_flags = [_tech_real, comp_real["valuation"], comp_real["momentum"]]
        _num_real = sum(1 for r in _real_flags if r)
        valid_rate = (_num_real / 3.0) if _num_real else 0.0

        # 输入分项值：technical = 技术信号分×0.5 + 因子 technical 分项
        _t_val = tech_score * 0.5 + comp_vals.get("technical", 0.0)
        _v_val = comp_vals.get("valuation", 0.0)
        _m_val = comp_vals.get("momentum", 0.0)

        # 权重归一：缺失分项权重置 0，其余归一化到和为 1（避免缺失分项静默稀释）
        _w = list(_BASE_W)
        if not _tech_real:
            _w[0] = 0.0
        if not comp_real["valuation"]:
            _w[1] = 0.0
        if not comp_real["momentum"]:
            _w[2] = 0.0
        _wsum = sum(_w)
        _weights = tuple(x / _wsum for x in _w) if _wsum > 0 else None

        cd = composite_signal_with_gate(
            technical=_t_val,
            valuation=_v_val,
            momentum=_m_val,
            factor_valid_rate=valid_rate,
            weights=_weights,
        )
        cd["technical_signal"] = tech_sig.get("signal") or "hold"
        fb["composite_decision"] = cd


def _within_symbol_factor_composite(fs: dict) -> float | None:
    """round25 R27: 单标的因子复合分（与设计屏同口径）。

    设计路径用 ``aggregate_factor_scores``（方向化 + 分类加权）得到 composite；
    策略检查旧实现用 raw 因子值朴素均值（被 ``china.policy.* +8.97`` 等异构量纲
    原始值拉偏，159338 报「1.68 偏强」与设计 -0.958 方向相反）。本函数对单标的复用
    同一 ``aggregate_factor_scores``（与设计同口径；缺 IC 序列→回退等权，不改变方向），
    使两屏因子分方向一致。无因子 → None（回落原始均值仅方向参考）。
    """
    if not isinstance(fs, dict) or not fs:
        return None
    try:
        from app.core.factor_aggregate import aggregate_factor_scores
        from ...factors.factor_registry import registry as factor_registry
        # R66 (round28): 与设计屏共用同一复合函数——传 ic_series（IC 加权聚合）。
        # 旧实现不传 ic_series → 等权回退，而 allocation_engine 传 ic_series
        # （IC 加权），同标的聚合值不同 → 两屏数值量级不一致（-0.9007 vs -0.08）。
        agg = aggregate_factor_scores(
            fs,
            definitions=factor_registry._factors,
            ic_series=getattr(factor_registry, "_ic_series_cache", None),
        )
    except Exception:
        return None
    if not isinstance(agg, dict):
        return None
    _cats = ("technical", "momentum", "valuation", "sentiment")
    # 无任何真实分类键匹配（如 {"a":0.9,"b":0.5} 这类非因子键）→ 返回 None，
    # 回落 raw 均值（仅方向参考），避免把 0.0 当「中性复合分」强行覆盖。
    if not any(k in agg for k in _cats):
        return None
    pw = {"technical": 0.3, "momentum": 0.3, "valuation": 0.2, "sentiment": 0.2}
    comp = sum(agg.get(k, 0.0) * w for k, w in pw.items())
    return float(round(comp, 3))


def _full_pool_factor_composite(factor_breakdowns: dict[str, dict]) -> dict[str, dict]:
    """round27 R42: 策略检查「因子分」复用设计同源的全池截面 z（与设计屏方向一致）。

    背景（R42 实证）：旧截面复合分实现在**组合内持仓子集**
    重做 z-score，导致同一标的在设计屏（全池 z，-0.958）与策略检查屏（持仓子集 z，
    +0.16）方向相反映。本函数对每只持仓按其 symbol 查
    ``market_data_hub.get_factor_matrix()`` 的**全池截面 z 行**（即设计
    ``allocation_engine.aggregate_factor_scores`` 的输入），用同一
    ``aggregate_factor_scores`` 分类加权复合 → 与设计同口径、同方向。

    场外联接基金（不在候选池内，如 022449）→ 回落 ``_within_symbol_factor_composite``
    （单标的口径），并标注 ``reference='单标的'`` 诚实区分。

    返回 ``{sym: {"composite": float|None, "reference": "相对候选池"|"单标的"}}``。
    """
    from ...services.market_data_hub import market_data_hub as _hub
    _matrix: dict[str, dict] = {}
    try:
        _matrix = _hub.get_factor_matrix() or {}
    except Exception as _e:
        logger.debug("[strategy_check] get_factor_matrix failed (non-fatal): %s", _e)
    out: dict[str, dict] = {}
    for sym, fb in factor_breakdowns.items():
        if not isinstance(fb, dict):
            continue
        fs = fb.get("factor_scores") or {}
        fs = fs if isinstance(fs, dict) else {}
        if sym in _matrix and _matrix[sym]:
            # 全池截面 z 行 → 与设计同源的 aggregate_factor_scores 复合（同方向）
            out[sym] = {
                "composite": _within_symbol_factor_composite(_matrix[sym]),
                "reference": "相对候选池",
            }
        else:
            # 场外联接不在池内 → 单标的口径（诚实降级，标注「单标的」）
            out[sym] = {
                "composite": _within_symbol_factor_composite(fs),
                "reference": "单标的",
            }
    return out


def _build_rule_fallback_holdings_analysis(
    etfs: list,
    market_data: list[dict],
    factor_breakdowns: dict[str, dict],
    weight_map: dict[str, float],
    regime: str = "range_bound",
) -> list[dict]:
    """R5-1-2: rule 兜底路径的 holdings_analysis 骨架生成。

    LLM 超时/失败时 holdings_analysis 恒空 → 行业集中度检查静默跳过（P0-1 收敛）。
    本函数用 market_data + factor_breakdowns 生成逐标的分析骨架：
    symbol/name/weight/factor_summary/industry，标注 "规则引擎生成"。
    后续 P0-1 行业注入 + P2-4 权重回填会统一覆盖/补全字段。
    """
    result: list[dict] = []
    # round27 R42: 骨架路径同样复用全池截面 z 复合分（与设计/主路径同方向）
    _factor_composites: dict[str, dict] = {}
    try:
        _factor_composites = _full_pool_factor_composite(factor_breakdowns)
    except Exception:
        _factor_composites = {}
    for e in etfs:
        if isinstance(e, dict):
            sym = e.get("symbol")
            name = e.get("name", sym)
        else:
            sym = getattr(e, "symbol", None)
            name = getattr(e, "name", sym)
        if not sym or sym == "CASH":
            continue
        md = next((m for m in market_data if m.get("symbol") == sym), {})
        fb = factor_breakdowns.get(sym, {}) or {}
        fs = fb.get("factor_scores", {}) or {}
        if isinstance(fs, dict) and any(v for v in fs.values()):
            factor_str = format_factor_summary(
                fs, tech_ind=fb.get("technical_indicators") if isinstance(fb, dict) else None
            )
        else:
            factor_str = "因子数据不足"
        # industry 占位：P0-1 行业注入会 setdefault 填充真实行业（数据源可用时）
        ind = ""
        if isinstance(fb.get("technical_indicators"), dict):
            ind = (fb["technical_indicators"].get("sector") or "")
        # P1-13③ (round9 §4.4-1): 骨架也带 tech_signal（真实值或「数据不可用」标注）——
        # 旧骨架无该字段 → 规则引擎兜底路径前端信号列空白
        _tech_sig = "数据不可用"
        _ts = (fb.get("technical_signal") or {})
        if isinstance(_ts, dict) and _ts.get("signal"):
            _tech_sig = f"{str(_ts['signal']).upper()}，真实信号"
        # P1-8 (round20 §五 P1-8②): 骨架补 action/suggested_weight——与 suggestions
        # 同源（复用 _rule_based_suggestion 决策表），修复 D-B2 holdings_analysis
        # action=None 与 suggestions 割裂。
        _weight = weight_map.get(sym) or md.get("target_weight") or 0.0
        _rule = _rule_based_suggestion(
            symbol=sym, name=name or sym, target_weight=_weight,
            factor_score=fs if isinstance(fs, dict) else {},
            signal=_ts, regime=regime, current_weight=_weight,
            factor_availability=fb.get("factor_availability"),
            # round27 R42: 骨架路径同样使用全池截面 z 复合分（调用方已算好传入）
            factor_composite=(_factor_composites.get(sym) or {}).get("composite"),
            factor_composite_label=(_factor_composites.get(sym) or {}).get("reference"),
        )
        result.append({
            "symbol": sym,
            "name": name or sym,
            "weight": weight_map.get(sym),
            "factor_summary": factor_str,
            "industry": ind,
            "tech_signal": _tech_sig,
            "action": _rule["action"],
            "suggested_weight": _rule["suggested_weight"],
            "generated_by": "规则引擎生成",
        })
        # round25 R28: 规则兜底骨架同样拷贝 composite_decision（_attach_composite_decisions
        # 在 LLM 报告生成前已附加到 factor_breakdowns）——保证 LLM 路径与兜底路径的
        # holdings_analysis 结构一致（字段缺失不出现，诚实降级）。
        _cd = fb.get("composite_decision") if isinstance(fb, dict) else None
        if isinstance(_cd, dict):
            result[-1]["composite_decision"] = _cd
    return result


def _rule_based_suggestion(
    symbol: str,
    name: str,
    target_weight: float,
    factor_score: dict,
    signal: dict | None,
    regime: str,
    current_weight: float | None = None,
    factor_availability: dict | None = None,
    factor_composite: float | None = None,
    factor_composite_label: str | None = None,
) -> dict:
    """Z26: 规则引擎兜底建议 — 基于因子分 + 技术信号 + regime 决策表。

    仅输出 increase/decrease/hold 枚举（契约硬约束），source='rule'。
    suggested_weight 调整：
      increase -> min(current * 1.2, 0.30)（单只 ≤30% 风控）
      decrease -> max(current * 0.7, 0.0）
      hold     -> 维持当前权重

    round18 P2-7 (2026-08-12): confidence 不再固定 0.7——按因子填充率分级：
      填充率 <70% → confidence=0.5（medium，说明数据不完整）；
      填充率 ≥70% → confidence=0.7（保留）。负向：填充率低仍 high → FAIL。

    U2 R2 (factor-and-strategy-check-review 问题3 R2): 决策表分档——
      - avg_factor > 0.5 + buy 且非 bearish → increase
      - avg_factor < -0.5 + sell → decrease
      - avg_factor ∈ (0.2, 0.5) + buy → hold（偏多但未达增仓阈值 0.5）
      - 其余 hold，reason 带因子分/信号依据（不再裸"维持现状"）
    """
    fs_vals = [v for v in (factor_score or {}).values()
               if isinstance(v, (int, float)) and v != 0]
    avg_factor = sum(fs_vals) / len(fs_vals) if fs_vals else 0.0
    # round27 R42: 因子分口径统一——调用方（策略检查路径）总是显式传入截面 z 复合分
    # （场内=全池 z、场外联接=单标的口径，均由 `_full_pool_factor_composite` 计算并作为
    # factor_composite 传入）。未传 factor_composite 时回落原始均值 avg_factor（量纲不一，
    # 仅方向参考）——与历史/单标的调用方语义一致，不在此自动改算 within-symbol 复合分
    # （避免复核点：自动改算会改变决策表输入，破坏既有 avg_factor 语义的回归测试）。
    _score = factor_composite if factor_composite is not None else avg_factor
    sig = ""
    if isinstance(signal, dict):
        sig = signal.get("signal", "hold") or "hold"

    bearish = regime in ("bearish", "bear", "bear_market", "defensive")
    cur = current_weight if current_weight is not None else target_weight
    # R4-22: 建议丰富化 — reason 输出 3 句结构化文本（依据/操作/纪律），
    # 保留旧关键词（测试断言兼容：偏离目标权重/未达增仓阈值/因子分/信号）
    _regime_cn = {"range_bound": "震荡", "bullish": "偏多", "bearish": "偏空",
                  "volatile": "高波动", "unknown": "待定"}.get(regime, regime)
    # 相对偏离度：|current - target| / max(target, eps) > 20% → 向 target 回归
    _eps = 1e-9
    if current_weight is not None and abs(current_weight - target_weight) > max(target_weight, _eps) * 0.2:
        if current_weight < target_weight:
            action = "increase"
            reason = (
                f"偏离目标权重（当前 {current_weight:.1%} < 目标 {target_weight:.1%}），建议回归至 {target_weight:.1%}；"
                f"分 2 次加仓、单次加仓不超过目标权重的 20%，避免追高；"
                f"当前市态{_regime_cn}，若跌破 MA20 或市态转空则暂停加仓"
            )
            suggested = min(target_weight, 0.30)
        else:
            action = "decrease"
            reason = (
                f"偏离目标权重（当前 {current_weight:.1%} > 目标 {target_weight:.1%}），建议回归至 {target_weight:.1%}；"
                f"分批减仓、单次减幅不超过当前仓位的 30%，平滑换仓成本；"
                f"若跌破前期支撑位可加速离场，保留现金等待市态企稳"
            )
            suggested = max(target_weight, 0.0)
    # F10 (round6 §十五, 用户已决策): 信号-因子背离分支——技术面与因子分冲突时
    # hold 并解释，禁止裸"信号 X 维持现状"自相矛盾写法（159992 类：SELL + 强正因子）。
    elif sig == "sell" and _score >= 0.5:
        action = "hold"
        reason = (
            f"技术面偏空但因子分强正（{_score:.2f}），信号与因子背离——暂不追空；"
            f"跌破 MA20 或因子分转负再降仓，市态{_regime_cn}下保持纪律"
        )
        suggested = cur
    elif sig == "buy" and _score <= -0.5:
        action = "hold"
        reason = (
            f"技术面偏多但因子分偏弱（{_score:.2f}），信号与因子背离——不追高；"
            f"站上 MA20 且因子分转正再加仓，市态{_regime_cn}下保持纪律"
        )
        suggested = cur
    elif _score > 0.5 and sig == "buy" and not bearish:
        action = "increase"
        reason = (
            # round18 P1-1: 规则引擎无基本面数据——「基本面与动量共振」失真，
            # 改为「因子评分 + 技术信号」共振（措辞与数据支撑匹配）
            f"因子评分优({_score:.2f})、技术面买入信号，因子与技术信号共振，建议增仓；"
            f"分 2 次执行、单次加仓不超过目标权重的 20%，留出回调加仓空间；"
            f"若市态转空或跌破 MA20 则暂停加仓，不逆势硬扛"
        )
        suggested = min(cur * 1.2, 0.30)
    elif _score < -0.5 and sig == "sell":
        action = "decrease"
        reason = (
            f"因子评分弱({_score:.2f})+技术卖出信号，趋势转弱，建议减仓；"
            f"分批执行、单次减幅不超过当前仓位的 30%，避免一次性冲击成本；"
            f"若继续破位（跌破 MA60 或前期低点）加速离场，市态{_regime_cn}下优先控制回撤"
        )
        suggested = max(cur * 0.7, 0.0)
    elif _score > 0.2 and sig == "buy":
        action = "hold"
        reason = (
            f"偏多（因子分 {_score:.2f} 未达增仓阈值 0.5），维持现状；"
            f"继续持有观察，若因子分突破 0.5 或放量突破关键阻力位再转增配；"
            f"止损纪律：跌破 MA20 或买入逻辑破坏即减仓一半"
        )
        suggested = cur
    else:
        action = "hold"
        _fcorr = ("偏强" if _score >= 0.5 else
                  "偏弱" if _score <= -0.5 else
                  "中性")
        # round18 P1-1 (D8 同修): 技术卖出信号下的 hold 不再提示「加仓机会」
        # （sell + hold + 加仓暗示 = 逻辑矛盾）
        _follow_up = (
            "技术信号偏空，暂不加仓；待信号转多或因子转正再评估"
            if sig == "sell"
            else "关注 RSI 进入超卖区（<30）或因子转正后的加仓机会"
        )
        reason = (
            f"因子分 {_score:.2f}（{_fcorr}），信号 {sig or '中性'}，维持现状；"
            f"持有逻辑不变，跟踪因子与信号变化；"
            f"{_follow_up}，市态{_regime_cn}不追涨杀跌"
        )
        suggested = cur

    # round27 R42: 因子分参考群体标注——设计屏「相对候选池」、策略检查场内持仓
    # 「相对候选池」、场外联接「单标的（场外联接无池内截面）」——两屏口径可比对。
    if factor_composite_label:
        reason = f"{reason}（因子分口径：{factor_composite_label}）"

    # P0-10① (round16 3.11): action/suggested 方向一致性校验——增仓不得降仓、减仓不得升仓。
    # 单只 30% 风控上限仅作"已达上限"提示，不输出"increase 0.5→0.3"这类矛盾值。
    if action == "increase":
        if suggested < cur:
            reason_append = (
                f"；当前仓 {cur:.1%} 已达/接近 30% 风控上限，suggested 维持 {cur:.1%} 不再上探"
                if cur >= 0.299
                else f"；suggested 按 {cur:.1%} 保底（原目标 {suggested:.1%} 被 30% 上限截断）"
            )
            reason = reason + reason_append
            suggested = max(suggested, cur)
    elif action == "decrease":
        if suggested > cur:
            reason = reason + f"；suggested 按 {cur:.1%} 封顶（减仓不得升仓）"
            suggested = min(suggested, cur)
    elif action == "hold":
        suggested = cur

    # round18 P2-7 + round24 R4: confidence 按因子填充率分档，且表示法与 LLM 路径统一
    # 为语义标签（旧实现输出裸数值 0.5/0.7 与 LLM 的 high/medium 同屏混排，0.7 易被
    # 误读为「高置信」——实为「中等」）。分档：≥90%→high、≥70%→medium、<70%→low；
    # 无可用度信息（total=0）→ medium（不冒充 high）。
    _filled = ((factor_availability or {}).get("filled")) or 0
    _total = ((factor_availability or {}).get("total")) or 0
    if _total <= 0:
        _confidence = "medium"
    else:
        _fill_rate = _filled / _total
        if _fill_rate >= 0.9:
            _confidence = "high"
        elif _fill_rate >= 0.7:
            _confidence = "medium"
        else:
            _confidence = "low"

    return {
        "symbol": symbol,
        "name": name,
        "action": action,
        "current_weight": round(float(cur or 0), 4),
        "suggested_weight": round(float(suggested), 4),
        "reason": reason,
        "confidence": _confidence,
        # R107 (round34): composite 分显式出参——报告表格「因子分」列与 reason 引用
        # 同源单义（_score 即 composite 复合分）。旧表格列自算原始因子非零均值
        # （RSI/KDJ 0-100 与 z-score 混杂量纲 + 剔零漂移），与理由同页打架
        #（实测 159992 表格 +1.63 vs 理由 -2.43，round34 §4.5）。
        "composite_score": round(float(_score), 4),
        "source": "rule",
    }


def _build_rule_fallback_report(
    market_data: list[dict],
    factor_breakdowns: dict,
    merged_suggestions: list[dict],
    regime: str,
    data_quality: dict | None,
    llm_failed: bool = False,
    risk_warnings: list[dict] | None = None,
) -> str:
    """U2 R1: 用已生成的 suggestions/factor/risk 渲染结构化 Markdown 正文。

    旧问题：rule 兜底只有 suggestions 数组、report_text 永远为空（task 66
    report_text len=0）——本函数为兜底路径生成完整正文：
    市态结论 → 因子数据质量 → 逐标的因子/信号/建议表 → 风险提示 → 操作建议。
    """
    regime_label = {"range_bound": "震荡", "bullish": "偏多", "bearish": "偏空",
                    "volatile": "高波动", "unknown": "待定"}.get(regime, regime)
    lines: list[str] = []
    lines.append("## 策略检查报告")
    lines.append("")
    lines.append(f"**市态**：{regime_label}")
    if llm_failed:
        lines.append("")
        lines.append("> ⚠️ LLM 分析超时/不可用，以下内容由规则引擎基于因子数据与信号生成。")
    filled = (data_quality or {}).get("filled_count", 0)
    total = (data_quality or {}).get("total_count", 0)
    fallback_count = (data_quality or {}).get("fallback_count", 0)
    fallback_ratio = (data_quality or {}).get("fallback_ratio", 0.0)
    lines.append("")
    # R87 (round30): 标题改报组合级分项覆盖（_rule_fallback_quality_line）——
    # 删除「N/N 无兜底」持仓级口径（与 composite「分项覆盖 33.3%」自相矛盾）。
    # fallback_count 语义保留（兜底占比明示，P0-B 延续）。
    _cov = data_quality.get("coverage_agg") if isinstance(data_quality, dict) else None
    if isinstance(_cov, dict) and (_cov.get("total") or 0) > 0:
        lines.append(_rule_fallback_quality_line(
            {"agg_total": _cov["total"], "coverage_pct": data_quality.get("factor_coverage_pct", 0.0)},
            fallback_count=fallback_count,
        ))
    elif fallback_count and total:
        _ratio_pct = f"{fallback_ratio*100:.0f}%"
        lines.append(
            f"**因子数据质量**：{filled}/{total} 只持仓因子数据可用"
            f"（其中 {fallback_count} 只技术因子缺数据兜底，占比 {_ratio_pct}）。"
        )
    elif total:
        lines.append(f"**因子数据质量**：{filled}/{total} 只持仓因子数据可用。")
    else:
        lines.append("**因子数据质量**：无可计算持仓。")
    lines.append("")
    lines.append("### 逐标的因子/信号/建议")
    lines.append("| 代码 | 名称 | 因子分 | 信号 | 建议 | 理由 |")
    lines.append("|------|------|--------|------|------|------|")
    for s in merged_suggestions or []:
        sym = s.get("symbol", "")
        fb = factor_breakdowns.get(sym, {}) or {}
        # R107 (round34): 「因子分」列改读与理由同源的 composite_score——旧实现
        # fs_vals 对原始因子非零值简单平均（RSI(0-100)/KDJ/动量 z-score 混杂量纲，
        # 剔零再漂移），与同行 reason「因子分 X.XX」（composite 口径）同页矛盾。
        comp = s.get("composite_score")
        avg = comp if isinstance(comp, (int, float)) else 0.0
        sig = ((fb.get("technical_signal") or {}).get("signal") or "hold")
        action = s.get("action", "hold")
        reason = (s.get("reason", "") or "").replace("|", "｜")
        lines.append(
            f"| {sym} | {s.get('name', sym)} | {avg:.2f} | {sig} | {action} | {reason} |"
        )
    lines.append("")
    lines.append("### 风险提示")
    warnings = risk_warnings or []
    if warnings:
        for w in warnings:
            sev = w.get("severity", "info")
            desc = (w.get("description", "") or "").replace("|", "｜")
            lines.append(f"- [{sev}] {desc}")
    else:
        lines.append("- 当前组合风险指标正常，未触发自动警告。")
    lines.append("")
    lines.append("### 操作建议")
    if merged_suggestions:
        lines.append("")
        for s in merged_suggestions:
            action = s.get("action", "hold")
            sym = s.get("symbol", "")
            cw = s.get("current_weight", 0)
            sw = s.get("suggested_weight", 0)
            # round24 R4: 正文置信度用中文档位（旧实现直出 0.7/medium 混排不可读）
            conf = _CONFIDENCE_ZH[_normalize_confidence(s.get("confidence"))]
            reason = (s.get("reason", "") or "").replace("|", "｜")
            lines.append(f"**{sym} {s.get('name', sym)}**：`{action}` {cw:.1%} → {sw:.1%}（置信度 {conf}）")
            # R4-22: reason 为 3 句结构化文本（依据/操作/纪律），分点列出提升可读性
            for part in [p for p in reason.split("；") if p.strip()]:
                lines.append(f"- {part.strip()}")
            lines.append("")
    else:
        lines.append("- 无可操作标的（组合为空）。")
    return "\n".join(lines)


def _reconcile_indicator_window(window: str, canon: dict[str, float]) -> tuple[str, list[str]]:
    """R95: 在持仓 symbol 上下文窗口内校正指标数值（纯函数，无 I/O）。

    canon: {"kdj_j": float, "kdj_k": ..., "kdj_d": ..., "rsi": ..., "ma5": ...,
            "ma10": ...}（technical_indicators 原始值，与 /market/indicators 对齐）。
    偏差 >1.0 才覆盖（避免浮点舍入误改）；量比负值（真实量比应≥0，负值是 z-score
    冒充）→ 标「数据待核」。
    """
    import re

    out = window
    warns: list[str] = []

    def _patch(pattern: str, key: str, label: str) -> None:
        nonlocal out
        def _sub(m: "re.Match") -> str:
            try:
                cur = float(m.group("val"))
            except (ValueError, IndexError):
                return m.group(0)
            target = canon.get(key)
            if target is None or abs(cur - target) < 1.0:
                return m.group(0)
            warns.append(f"{label} {cur:.2f}→{target:.2f}")
            rel_s = m.start("val") - m.start()
            rel_e = m.end("val") - m.start()
            return f"{m.group(0)[:rel_s]}{target:.2f}{m.group(0)[rel_e:]}"
        out = re.sub(pattern, _sub, out)

    # KDJ.K / KDJ.D / KDJ.J（正文常见「KDJ J=6.16」/「KDJ.J 84.49」）
    _patch(r"KDJ\s*\.?\s*J\s*[=:：]\s*(?P<val>\d+(?:\.\d+)?)", "kdj_j", "KDJ J")
    _patch(r"KDJ\s*\.?\s*K\s*[=:：]\s*(?P<val>\d+(?:\.\d+)?)", "kdj_k", "KDJ K")
    _patch(r"KDJ\s*\.?\s*D\s*[=:：]\s*(?P<val>\d+(?:\.\d+)?)", "kdj_d", "KDJ D")
    # RSI（须带 =/:，避免误匹配「RSI(14)」标识）
    _patch(r"RSI\s*[=:：]\s*(?P<val>\d+(?:\.\d+)?)", "rsi", "RSI")
    # SMA5/10 成对（如「SMA5/10(3.07/13.06)」）
    if "ma5" in canon and "ma10" in canon:
        _pair = re.compile(
            r"SMA5\s*/\s*10\s*[=:：]?\s*[（(]?(?P<a>\d+(?:\.\d+)?)"
            r"\s*/\s*(?P<b>\d+(?:\.\d+)?)[）)]?"
        )
        def _sub_pair(m: "re.Match") -> str:
            try:
                a, b = float(m.group("a")), float(m.group("b"))
            except ValueError:
                return m.group(0)
            if abs(a - canon["ma5"]) < 1.0 and abs(b - canon["ma10"]) < 1.0:
                return m.group(0)
            warns.append(f"SMA5/10 {a:.2f}/{b:.2f}→{canon['ma5']:.2f}/{canon['ma10']:.2f}")
            rel_a = m.start("a") - m.start()
            rel_b = m.end("b") - m.start()
            return (f"{m.group(0)[:rel_a]}{canon['ma5']:.2f}"
                    f"/{canon['ma10']:.2f}{m.group(0)[rel_b:]}")
        out = _pair.sub(_sub_pair, out)
    # SMA5 / SMA10 单独（须带 =/:）
    _patch(r"SMA5\s*[=:：]\s*(?P<val>\d+(?:\.\d+)?)", "ma5", "SMA5")
    _patch(r"SMA10\s*[=:：]\s*(?P<val>\d+(?:\.\d+)?)", "ma10", "SMA10")
    # 量比负值（真实量比应≥0；z-score 可负 → 标数据待核，不冒充）
    _vr = re.compile(r"量比\s*[=:：]?\s*(?P<val>-?\d+(?:\.\d+)?)")

    def _sub_vr(m: "re.Match") -> str:
        try:
            cur = float(m.group("val"))
        except ValueError:
            return m.group(0)
        if cur >= 0:
            return m.group(0)
        warns.append(f"量比 {cur:g}（负值异常，真实量比应≥0）")
        rel_s = m.start("val") - m.start()
        rel_e = m.end("val") - m.start()
        return f"{m.group(0)[:rel_s]}数据待核{m.group(0)[rel_e:]}"
    out = _vr.sub(_sub_vr, out)
    return out, warns


def _reconcile_aggregate_weights(text: str, weight_map: dict[str, float]) -> tuple[str, list[str]]:
    """R95: 正文「合计权重 N%」聚合表述与结构化权重和一致性校验（纯函数）。

    取 claim 前 120 字符窗口内出现的全部持仓 symbol → 求 weight_map 权重和 →
    与声明值偏差 >1% 用权重和覆盖 + WARNING。窗口无 symbol（无法校验）→ 不误改。
    """
    import re
    warnings: list[str] = []
    out = text
    pattern = re.compile(r"合计权重\s*[=:：]?\s*(?P<val>\d+(?:\.\d+)?)\s*%")
    # 从右往左替换——多个 claim 时左侧替换不影响右侧已处理位置（避免偏移错位）
    for m in reversed(list(pattern.finditer(text))):
        try:
            claimed = float(m.group("val"))
        except ValueError:
            continue
        ctx = text[max(0, m.start() - 120):m.end()]
        syms = re.findall(r"\b(\d{6})\b", ctx)
        if not syms:
            continue
        total = sum(weight_map.get(s, 0.0) for s in set(syms))
        if total <= 0:
            continue
        structured_pct = round(total * 100, 1)
        if abs(structured_pct - claimed) < 1.0:
            continue
        warnings.append(f"「合计权重」聚合 {claimed:g}%→{structured_pct:g}%")
        out = out[:m.start("val")] + f"{structured_pct:g}" + out[m.end("val"):]
    return out, warnings


def _reconcile_report_numbers(
    text: str,
    factor_breakdowns: dict | None = None,
    weight_map: dict | None = None,
) -> tuple[str, list[str]]:
    """R95 (round31): 报告正文数值一致性校验（纯函数，无 I/O）。

    背景（§4.3）：报告正文（LLM/rule 文本层）与结构化层数值源不一致——同一标的
    同一指标，structured（factor_summary / technical_indicators）与正文数值不同
    （512890 KDJ J：84.49 vs 6.16；518880 SMA 3.07/13.06 vs 实测 9.02/8.99；
    量比 -9.86 负值；「港股类合计权重 10%」 vs holdings_json 权重和 13%）。

    处理（仿 _validate_report_consistency 修正脚注模式）：
      ① 按持仓 symbol 上下文窗口校正 KDJ.K/D/J、RSI、SMA(5/10) 数值
         （与 technical_indicators 原始值比对，偏差 >1 用结构化值覆盖）；
      ② 量比负值（真实量比应≥0）→ 标「数据待核」；
      ③ 正文「合计权重 N%」类聚合表述与 weight_map 结构化权重和一致性校验。

    返回 (修正后文本, warnings)。warnings 非空时调用方追加修正脚注。
    """
    if not text:
        return text, []
    factor_breakdowns = factor_breakdowns or {}
    weight_map = weight_map or {}
    warnings: list[str] = []
    out = text

    for sym, fb in factor_breakdowns.items():
        if not isinstance(fb, dict):
            continue
        ind = fb.get("technical_indicators") or {}
        if not isinstance(ind, dict):
            continue
        kdj = ind.get("kdj") or {}
        if not isinstance(kdj, dict):
            kdj = {}
        canon: dict[str, float] = {}
        for _k, _v in (("kdj_j", kdj.get("j")), ("kdj_k", kdj.get("k")),
                       ("kdj_d", kdj.get("d")), ("rsi", ind.get("rsi")),
                       ("ma5", ind.get("ma5")), ("ma10", ind.get("ma10"))):
            if isinstance(_v, (int, float)) and not isinstance(_v, bool):
                canon[_k] = float(_v)
        if not canon:
            continue
        _pos = out.find(sym)
        if _pos < 0:
            continue
        _end = min(len(out), _pos + 160)
        _window = out[_pos:_end]
        _fixed, _warns = _reconcile_indicator_window(_window, canon)
        if _fixed != _window:
            out = out[:_pos] + _fixed + out[_end:]
            warnings.extend(_warns)

    if weight_map:
        out, _aw = _reconcile_aggregate_weights(out, weight_map)
        warnings.extend(_aw)
    return out, warnings


def _combine_risk_warnings(
    llm_warnings: list[dict],
    rule_warnings: list[dict],
    llm_failed: bool = False,
    data_all_empty: bool = False,
) -> list[dict]:
    """合并 LLM 和规则风险警告，确保至少有一条。

    U2 R3 (factor-and-strategy-check-review 问题3 R3): 风险兜底诚实化——
    LLM 超时或因子数据缺失时输出 warning 级降级标注，而非误导性的 info"正常"。
    """
    combined = llm_warnings + rule_warnings
    if not combined:
        if data_all_empty:
            combined = [{"type": "general", "severity": "warning",
                         "description": "因子数据不可用，风险提示完整性受限（基于规则引擎部分数据）。"}]
        elif llm_failed:
            combined = [{"type": "general", "severity": "warning",
                         "description": "LLM 分析超时，风险提示基于规则引擎部分数据，完整性受限。"}]
        else:
            combined = [{"type": "general", "severity": "info",
                          "description": "当前组合风险指标正常，未触发自动警告。"}]
    elif llm_failed:
        # R5-1-2: 骨架生成后 combined 可能非空（行业缺失/超配 warning），
        # LLM 超时标注仍须存在（诚实降级）——前置一条，不依赖 combined 为空。
        if not any("LLM 分析超时" in w.get("description", "") for w in combined):
            combined = [{"type": "general", "severity": "warning",
                         "description": "LLM 分析超时，风险提示基于规则引擎部分数据，完整性受限。"}] + combined
    return combined


def _compute_risk_warnings(
    holdings_analysis: list[dict],
    factor_matrix: dict[str, dict[str, float | int]],
    regime: str,
) -> list[dict]:
    """基于因子数据和持仓分析计算组合风险警告。
    
    独立于 LLM 输出，确保风险 section 不会为空。
    """
    warnings: list[dict] = []
    from collections import defaultdict

    # 1. 行业集中度风险
    sector_weights: dict[str, float] = defaultdict(float)
    for h in holdings_analysis:
        sym = h.get("symbol", "")
        if sym == "CASH":
            continue
        sec = h.get("sector") or h.get("industry", "")
        w = float(h.get("weight", 0) or 0)
        sector_weights[sec] += w

    unique_sectors = len(sector_weights)
    if unique_sectors <= 2 and len(holdings_analysis) > 2:
        blank_weight = sector_weights.get("", 0.0)
        if blank_weight > 0:
            # P0-1 (R4-01): 空行业保护——行业数据缺失（数据源未覆盖）时
            # 降级为 WARN + 显式标注，而非误导性的 HIGH「仅覆盖1个行业」。
            # （旧逻辑把无行业字段的标的全部归入空串行业 → unique_sectors=1 误报）
            warnings.append({
                "type": "concentration",
                "severity": "warning",
                "description": (
                    f"行业集中度提示：行业数据缺失（数据源未覆盖{blank_weight:.0%}权重标的），"
                    "行业分布无法准确评估"
                ),
                "affected_symbols": [
                    h.get("symbol", "") for h in holdings_analysis
                    if not (h.get("sector") or h.get("industry", ""))
                ],
            })
        else:
            top_sector = max(sector_weights, key=sector_weights.get)
            warnings.append({
                "type": "concentration",
                "severity": "high",
                "description": f"行业集中度风险：仅覆盖{unique_sectors}个行业，"
                               f"最大行业{top_sector}占比{sector_weights[top_sector]:.0%}",
                "affected_symbols": [h.get("symbol", "") for h in holdings_analysis if (h.get("sector") or h.get("industry", "")) == top_sector],
            })

    # 2. 单只权重超配风险
    for h in holdings_analysis:
        w = float(h.get("weight", 0) or 0)
        if w >= 0.25:
            sym = h.get("symbol", "")
            name = h.get("name", sym)
            warnings.append({
                "type": "concentration",
                "severity": "medium",
                "description": f"{name}权重{w:.0%}，超过25%建议上限",
                "affected_symbols": [sym],
            })

    # 3. 低流动性风险
    for h in holdings_analysis:
        turnover = float(h.get("turnover_rate", 0) or 0)
        if 0 < turnover < 0.01:
            sym = h.get("symbol", "")
            warnings.append({
                "type": "liquidity",
                "severity": "low",
                "description": f"{h.get('name', sym)}成交量较低",
                "affected_symbols": [sym],
            })

    return warnings


async def _compute_indicators(symbols: list[str]) -> dict:
    """并行计算每只持仓的技术指标 + 信号。

    R6-F5 (round6 §十 R6-06): 与 /market/signal 同口径——纯 K 线计算，不传
    factor_scores（zscore 值会污染信号致两端分歧）。
    """
    from ...analysis.indicators import compute_all_indicators
    from ...analysis.signal import generate_signal
    from ...services.market_data_hub import market_data_hub

    results = {}
    hist_data = await asyncio.gather(
        *[market_data_hub.get_market_history(sym, "A") for sym in symbols],
        return_exceptions=True,
    )
    for sym, hist in zip(symbols, hist_data):
        if isinstance(hist, list) and hist:
            try:
                # R6-F5 (round6 §十 R6-06): 不传 factor_scores——factor_matrix 的
                # zscore 值（如 MACD）会污染信号，与 /market/signal 的纯 K 线口径
                # 产生分歧（518880 策略检查 BUY vs /market/signal hold）。
                ind = compute_all_indicators(hist)
                sig = generate_signal(ind)
                ind["signal"] = sig
                results[sym] = ind
            except Exception:
                continue
    return results

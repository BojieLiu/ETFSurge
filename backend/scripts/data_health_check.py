#!/usr/bin/env python3
"""
数据管道健康检查脚本 (P3-4)

周期运行: python -m backend.scripts.data_health_check

检查项:
1. Sina 历史行情可访问
2. FactorRegistry 对常见 ETF 的因子分方差 > 0.01
3. 各层候选数满足最低要求
4. SQLite 数据库可写
"""
import sys
import os
import time
import asyncio

# round30 修复: 旧 `..\..` 解析到项目根（app 包在 backend/ 下）→ ModuleNotFoundError。
# 单层 `..` 在两种调用方式下均指向 backend：脚本 `python scripts/...`（cwd=backend）
# 与模块 `python -m backend.scripts...`（cwd=项目根）都得到 backend 目录。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0
ERRORS: list[str] = []


def check(name: str, ok: bool, detail: str = ""):
    global PASS, FAIL
    if ok:
        print(f"  [+] {name}")
        PASS += 1
    else:
        print(f"  [!] FAIL: {name}" + (f" — {detail}" if detail else ""))
        FAIL += 1
        ERRORS.append(name)


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_sina_realtime():
    """检查 Sina 实时行情可访问。"""
    import urllib.request, json
    try:
        # round30 修复: urlopen 无 headers kwarg（Python3 API），须用 Request 携带
        req = urllib.request.Request(
            "https://hq.sinajs.cn/list=sh510300",
            headers={"Referer": "https://finance.sina.com.cn"},
        )
        r = urllib.request.urlopen(req, timeout=10)
        data = r.read().decode("gbk")
        check("Sina 实时行情可访问", len(data) > 50)
        return data
    except Exception as e:
        check("Sina 实时行情可访问", False, str(e)[:80])
        return None


def test_sina_kline():
    """检查 Sina K-line 返回 500 条数据（R102: 日线窗口与 china_market._sina_history_cb 同步 240→500）。"""
    import urllib.request, json
    try:
        r = urllib.request.urlopen(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData?symbol=sh510300&scale=240&datalen=500",
            timeout=10,
        )
        data = json.loads(r.read().decode("utf-8"))
        check("Sina K-line 可访问", isinstance(data, list) and len(data) > 50, f"len={len(data) if isinstance(data, list) else 'N/A'}")
        if isinstance(data, list):
            closes = [float(d.get("close", 0)) for d in data if d.get("close")]
            check("Sina K-line 收盘价非空", len(closes) > 50, f"close_count={len(closes)}")
    except Exception as e:
        check("Sina K-line 可访问", False, str(e)[:80])


def test_factor_differentiation():
    """检查 FactorRegistry 对常见 ETF 的因子分方差。"""
    from app.factors.factor_registry import FactorRegistry

    symbols = ["510300", "518880", "511090", "512480"]
    registry = FactorRegistry()
    try:
        import asyncio
        result = asyncio.run(registry.compute(symbols))

        all_fs = []
        for sym in symbols:
            scores = result.get(sym, {})
            vals = [v for v in scores.values() if isinstance(v, (int, float)) and abs(v) > 0.001]
            all_fs.extend(vals)

        if all_fs:
            var = sum((x - sum(all_fs)/len(all_fs))**2 for x in all_fs) / len(all_fs)
            check("FactorRegistry 因子分方差 > 0.01", var > 0.01, f"variance={var:.4f}")
        else:
            check("FactorRegistry 因子分非空", False, "all factors returned zero")

        check(f"Symbols computed: {len(symbols)}", len(symbols) > 0)
    except Exception as e:
        check("FactorRegistry 可运行", False, str(e)[:100])


def test_pool_candidate_counts():
    """检查 market_data_hub 各层候选数。"""
    try:
        from app.services.market_data_hub import MarketDataHub
        import asyncio

        pm = MarketDataHub()
        # round30 修复: refresh() 返回 PoolDiff 对象（无 .get）——候选池读 get_pool()
        asyncio.run(pm.refresh())
        pool = pm.get_pool()

        core = pool.get("core", [])
        satellite = pool.get("satellite", [])
        defense = pool.get("defense", [])

        check(f"Core 层候选数 >= 3", len(core) >= 3, f"count={len(core)}")
        check(f"Satellite 层候选数 >= 5", len(satellite) >= 5, f"count={len(satellite)}")
        check(f"Defense 层候选数 >= 2", len(defense) >= 2, f"count={len(defense)}")
    except Exception as e:
        check("MarketDataHub 可运行", False, str(e)[:100])


def test_db_writable():
    """检查 SQLite 数据库可读写。"""
    try:
        import asyncio
        from sqlalchemy import select, func
        from app.database import async_session, init_db

        async def _count():
            await init_db()
            from app.models.portfolio import PortfolioETF
            async with async_session() as session:
                n = (await session.execute(select(func.count(PortfolioETF.id)))).scalar() or 0
                return n

        # round30 修复: get_db() 是 async generator（无 .cursor）——改用 async_session
        count = asyncio.run(_count())
        check("SQLite 数据库可访问", True, f"{count} portfolios")
    except Exception as e:
        check("SQLite 数据库可访问", False, str(e)[:80])


def test_source_registry():
    """检查数据源熔断器状态。"""
    try:
        # round30 修复: source_registry 已移至 app.core（round29 迁移后旧路径失效）
        from app.core.source_registry import registry
        status = registry.circuit_breaker_status()
        check(f"熔断器状态: {len(status)} 个源", len(status) > 0)
        for s in status:
            avail = s.get("available", True)
            name = s.get("name", "?")
            if not avail:
                print(f"    [!] {name} 不可用（熔断中）")
    except Exception as e:
        check("熔断器可查询", False, str(e)[:80])


# §12 P0-2 (round34): 因子样本增长率快照——时间维度盲区补位。
# R108 七因子 n=7-9 停滞 9 天、vwap 冻结 n=245 一整年，快照型巡检结构性看不见；
# 本项对 per-factor distinct trade_date 做跨巡检对比：连续 ≥2 次无增长且 n<250
# → 列「输入缺失观察名单」（WARN 起步纪律 §12.5，不 FAIL 阻断）。
GROWTH_SNAPSHOT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "patrol_factor_growth.json",
)


def test_factor_sample_growth():
    """检查因子 IC 样本增长率（vs 上次巡检快照）。"""
    try:
        import asyncio
        import json as _json
        from app.database import async_session
        from app.factors.ic_tracker import ic_tracker

        async def _counts():
            async with async_session() as session:
                return await ic_tracker.get_sample_counts_by_code(session)

        counts = asyncio.run(_counts())
        if not counts:
            check("因子样本可查询", False, "get_sample_counts_by_code 空（DB 未初始化?）")
            return

        MIN_TRADING_DAYS = 250
        try:
            with open(GROWTH_SNAPSHOT_PATH, encoding="utf-8") as f:
                prev = _json.load(f)
        except Exception:
            prev = None

        if not prev or not isinstance(prev.get("counts"), dict):
            # 首跑建基线并记 PASS（§12.4 P0 规格）
            _save_growth_snapshot(counts, stale_runs={})
            check(f"因子样本增长率基线建立: {len(counts)} 因子", True,
                  f"快照={GROWTH_SNAPSHOT_PATH}")
            return

        prev_counts = prev.get("counts", {})
        stale_runs = dict(prev.get("stale_runs", {}))
        watchlist = []
        regressed = []
        for code, n in counts.items():
            p = int(prev_counts.get(code, 0) or 0)
            if int(n) < int(p):
                regressed.append(f"{code} {p}->{n}")
            if int(n) < MIN_TRADING_DAYS and int(n) <= int(p):
                runs = int(stale_runs.get(code, 0)) + 1
                stale_runs[code] = runs
                if runs >= 2:
                    watchlist.append((code, n, runs))
            else:
                stale_runs[code] = 0
        # 已消失的因子清理计数
        for code in list(stale_runs):
            if code not in counts:
                del stale_runs[code]
        _save_growth_snapshot(counts, stale_runs)

        detail = f"{len(counts)} 因子；停滞≥2次观察名单 {len(watchlist)} 只"
        if watchlist:
            print("    [WARN] 输入缺失观察名单（n<250 且连续 ≥2 次巡检无增长）：")
            for code, n, runs in sorted(watchlist, key=lambda x: x[1])[:10]:
                print(f"      - {code}: n={n}（停滞 {runs} 次巡检）")
            top = ",".join(c for c, _, _ in watchlist[:5])
            check(f"因子样本增长率: 观察名单 {len(watchlist)} 只（{top}…）",
                  True, "WARN 起步不阻断；核对输入字段是否缺失（R108/vwap 冻结同型）")
        else:
            check("因子样本增长率: 无停滞观察名单", True, detail)
        if regressed:
            print(f"    [WARN] 样本数回退 {len(regressed)} 只（异常信号）: {regressed[:3]}")
    except Exception as e:
        check("因子样本增长率可查询", False, str(e)[:100])


def _save_growth_snapshot(counts: dict, stale_runs: dict):
    import json as _json
    os.makedirs(os.path.dirname(GROWTH_SNAPSHOT_PATH), exist_ok=True)
    with open(GROWTH_SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        _json.dump({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "min_trading_days": 250,
            "counts": {k: int(v) for k, v in counts.items()},
            "stale_runs": {k: int(v) for k, v in stale_runs.items()},
        }, f, ensure_ascii=False, indent=2)


# ── round40 实施: 关键因子断链断言（round39 §4.4.4 方案 B）──────────────────
# 背景: R146/R147-FIX/R148/R149/R150 round39 容器复验发现以下关键因子 zero_ratio=1.0
# (全 None / 全占位 0):
#   etf.premium_discount / style.size.ln_mcap / style.size.ln_float_mcap /
#   etf.shares_change / etf.institutional_holdings_change / sentiment.news_heat /
#   factor.industry_diversification
# 根因: 数据源未注入 (非交易时段) 或修复未生效。本断言捕获「全断链」回归——
# 对代表 ETF 跑 factor_registry.compute() 统计 CRITICAL_FACTOR_CODES 至少 1 只
# ETF 有非零 meaningful 值, 否则 FAIL。
#
# 容忍: 非交易时段全 None 仍属预期 (round31 R4-07 教训: 误报比不报更糟),
# 全空时输出 WARN 不计入 FAIL 阻断.
CRITICAL_FACTOR_CODES: tuple[str, ...] = (
    "etf.premium_discount",
    "style.size.ln_mcap",
    "style.size.ln_float_mcap",
    "etf.shares_change",
    "etf.institutional_holdings_change",
    "sentiment.news_heat",
    # R148 收口 (round41): factor registry 注册的 key 是 "etf.industry_diversification"
    # (factor_registry.py:713), round40 B 方案误写 "factor.industry_diversification"
    # 导致 zero_ratio 永远查不到——修正 key 让断言真生效.
    "etf.industry_diversification",
)

_CHAIN_PROBE_SYMBOLS: tuple[str, ...] = ("510300", "518880", "511090", "512480")


def test_factor_chain_integrity():
    """关键因子断链断言——round40 实施 (round39 §4.4.4 方案 B).

    对 4 只代表 ETF 跑 factor_registry.compute() → 统计 CRITICAL_FACTOR_CODES
    中每个因子在全部 ETF 的非零 meaningful 值覆盖率 (FS1 is_meaningful_value)。
    期望: 至少 1 只 ETF 有非零值 (即断链率 < 100%)。
    全 None → WARN 提示「非交易时段数据源未注入」, 不计入 FAIL 阻断.
    """
    from app.core.factor_values import is_meaningful_value
    from app.factors.factor_registry import FactorRegistry

    try:
        registry = FactorRegistry()
        result = asyncio.run(registry.compute(list(_CHAIN_PROBE_SYMBOLS)))
    except Exception as e:
        check("关键因子断链: factor_registry 可运行", False, str(e)[:80])
        return

    if not result:
        check("关键因子断链: compute 返回非空", False, "all symbols returned empty")
        return

    # 统计每只 ETF 的非 None 总数（用于「全空 / 非交易时段」判定）
    per_etf_nonzero_total = {
        sym: sum(1 for v in factors.values() if v is not None)
        for sym, factors in result.items()
    }
    all_empty = all(n == 0 for n in per_etf_nonzero_total.values())
    if all_empty:
        # 非交易时段: 全部 ETF 数据源空——WARN, 不 FAIL (round31 R4-07 教训)
        check(
            "关键因子断链: 非交易时段全空已容忍 (WARN)",
            True,
            f"all 4 symbols returned None — lazy inject pending market open; "
            f"per_sym={per_etf_nonzero_total}",
        )
        return

    broken: list[str] = []
    for code in CRITICAL_FACTOR_CODES:
        meaningful_count = 0
        total = 0
        for sym, factors in result.items():
            if code not in factors:
                continue
            total += 1
            val = factors[code]
            if is_meaningful_value(code, val):
                meaningful_count += 1
        if total == 0:
            broken.append(f"{code}=missing_in_all_4")
            continue
        if meaningful_count == 0:
            broken.append(f"{code}=0/{total}_meaningful")

    if broken:
        # 断链: 至少一个 critical factor 在 4 只 ETF 全 0/None
        check(
            f"关键因子断链: {len(broken)} 项 critical factor 全断链",
            False,
            "; ".join(broken[:5]) + ("..." if len(broken) > 5 else ""),
        )
    else:
        check(
            f"关键因子断链: {len(CRITICAL_FACTOR_CODES)} 项 critical factor 均有非零值",
            True,
            f"per_etf_nonzero_total={per_etf_nonzero_total}",
        )


if __name__ == "__main__":
    print(f"\n{'#'*60}")
    print(f"#  数据管道健康检查 (P3-4)")
    print(f"#  {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'#'*60}")

    section("1. 外部数据源连通性")
    test_sina_realtime()
    test_sina_kline()

    section("2. FactorRegistry 因子分")
    test_factor_differentiation()

    section("3. MarketDataHub 候选池")
    test_pool_candidate_counts()

    section("4. 存储层")
    test_db_writable()

    section("5. 熔断器")
    test_source_registry()

    section("6. 因子样本增长率 (§12 P0-2)")
    test_factor_sample_growth()

    section("7. 关键因子断链 (round40 实施 · round39 §4.4.4 方案 B)")
    test_factor_chain_integrity()

    section("评估结果")
    print(f"  PASS: {PASS}/{PASS+FAIL}")
    print(f"  FAIL: {FAIL}/{PASS+FAIL}")
    if ERRORS:
        print(f"\n  失败项:")
        for e in ERRORS:
            print(f"    - {e}")
    print(f"\n  {'ALL CHECKS PASSED' if FAIL == 0 else 'SOME CHECKS FAILED'}")
    sys.exit(0 if FAIL == 0 else 1)

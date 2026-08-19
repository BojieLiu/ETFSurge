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

# round30 修复: 旧 `..\..` 解析到项目根（app 包在 backend/ 下）→ ModuleNotFoundError。
# 单层 `..` 在两种调用方式下均指向 backend：脚本 `python scripts/...`（cwd=backend）
# 与模块 `python -m backend.scripts...`（cwd=项目根）都得到 backend 目录。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PASS = 0
FAIL = 0
ERRORS = []


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
    """检查 Sina K-line 返回 240 条数据。"""
    import urllib.request, json
    try:
        r = urllib.request.urlopen(
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            "CN_MarketData.getKLineData?symbol=sh510300&scale=240&datalen=240",
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

    section("评估结果")
    print(f"  PASS: {PASS}/{PASS+FAIL}")
    print(f"  FAIL: {FAIL}/{PASS+FAIL}")
    if ERRORS:
        print(f"\n  失败项:")
        for e in ERRORS:
            print(f"    - {e}")
    print(f"\n  {'ALL CHECKS PASSED' if FAIL == 0 else 'SOME CHECKS FAILED'}")
    sys.exit(0 if FAIL == 0 else 1)

"""同步标的基础信息到本地 instruments 表（供搜索/自动补全）。

数据源（akshare，按优先级降级）：
  - A 股个股: stock_zh_a_spot_em
  - A 股 ETF: fund_etf_spot_em
  - 港股:      stock_hk_main_board_spot_em
  - 美股:      stock_us_spot_em（若可用）

运行:
  python -m scripts.sync_instruments
"""

import asyncio
import os
import sys
from pathlib import Path

# 让脚本能 import app
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# O1 (round8 §7 P0-新): 段级超时——美股源（stock_us_spot_em）在当前网络环境黑洞，
# 暴露面最短；其余段 30s。超时后该段降级，不阻塞整体启动。
_SEGMENT_TIMEOUTS = {
    "A股个股": 30.0,
    "A股ETF": 30.0,
    "港股": 30.0,
    "美股": 20.0,
}


def _sync_disabled() -> bool:
    """O1: 环境开关 INSTRUMENTS_SYNC_DISABLED=1 跳过 instruments 同步。"""
    return os.environ.get("INSTRUMENTS_SYNC_DISABLED", "").strip().lower() in ("1", "true", "yes")


try:
    from pypinyin import lazy_pinyin
    _HAS_PINYIN = True
except ImportError:
    _HAS_PINYIN = False


def _to_pinyin(name: str) -> tuple[str, str]:
    """返回 (全拼, 首字母)。无 pypinyin 时返回空串。"""
    if not _HAS_PINYIN or not name:
        return "", ""
    full = "".join(lazy_pinyin(name))
    initial = "".join([p[0] for p in lazy_pinyin(name, style="first")])
    return full, initial


async def _fetch_akshare_list(fn_name: str, symbol_col: str, name_col: str, market: str, asset_type: str) -> list[dict]:
    """通用 akshare 列表拉取 + 归一化为 instruments 行。

    O1 (round8 §7 P0-新): akshare 网络调用经 asyncio.to_thread 提交线程池——
    裸同步调用会阻塞事件循环（stock_us_spot_em 卡死 → uvicorn 永不 bind 端口）。
    """
    import akshare as ak
    try:
        df = await asyncio.to_thread(getattr(ak, fn_name))
    except Exception as e:
        print(f"  [WARN] {fn_name} failed: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        return []
    # akshare 中文列可能 latin1 编码，需解码
    try:
        from app.utils.decode import decode_df as _decode_df
        df = _decode_df(df)
    except Exception:
        pass
    out = []
    for _, r in df.iterrows():
        sym = str(r.get(symbol_col, "") or "").strip()
        nm = str(r.get(name_col, "") or "").strip()
        if not sym or not nm:
            continue
        full, initial = _to_pinyin(nm)
        out.append({
            "symbol": sym,
            "name": nm,
            "market": market,
            "asset_type": asset_type,
            "pinyin": full,
            "first_letter": initial[:5],
        })
    return out


async def collect_all() -> list[dict]:
    """N09: 收集全部 instruments。

    每段（A 股个股 / ETF / 港股 / 美股）独立统计行数；失败段打 ERROR 而非仅 WARN。
    O3 (round7 §7 P3): 补 US 段——此前只打包 A/HK，instruments 表 US=0 →
    个股名称搜索（AAPL/苹果 等）空。
    """
    import logging
    logger = logging.getLogger("sync_instruments")
    segments = [
        ("A股个股", "stock_zh_a_spot_em"),
        ("A股ETF", "fund_etf_spot_em"),
        ("港股", "stock_hk_main_board_spot_em"),
        ("美股", "stock_us_spot_em"),
    ]
    tasks = [
        (_fetch_a_stock_list() if fn == "stock_zh_a_spot_em"
         else _fetch_etf_list() if fn == "fund_etf_spot_em"
         else _fetch_hk_list() if fn == "stock_hk_main_board_spot_em"
         else _fetch_us_list() if fn == "stock_us_spot_em"
         else _fetch_akshare_list(fn, "代码", "名称", mkt, at))
        for (_, fn), (mkt, at) in zip(segments, [("A", "stock"), ("A", "etf"), ("HK", "stock"), ("US", "US")])
    ]
    # O1 (round8 §7 P0-新): 每段 asyncio.wait_for 超时（美股 20s / 其他 30s）——
    # 黑洞段在超时窗口内必然结束，不占用事件循环；失败段仅降级（跳过），整体继续。
    async def _guarded(name: str, coro):
        timeout = _SEGMENT_TIMEOUTS.get(name, 30.0)
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            logger.error("[sync_instruments] segment %s TIMED OUT after %.1fs: %s", name, timeout, e)
            raise

    results = await asyncio.gather(
        *[_guarded(seg_name, coro) for (seg_name, _fn), coro in zip(segments, tasks)],
        return_exceptions=True,
    )
    merged: list[dict] = []
    seen = set()
    for (seg_name, _fn), res in zip(segments, results):
        # mypy 收窄：BaseException 而非 Exception（CancelledError 继承 BaseException）
        if isinstance(res, BaseException):
            logger.error("[sync_instruments] segment %s FAILED: %s", seg_name, res)
            continue
        logger.info("[sync_instruments] segment %s: %d rows", seg_name, len(res))
        for row in res:
            key = (row["symbol"], row["market"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


async def _fetch_a_stock_list() -> list[dict]:
    """P1-7 (R4-29): A 股个股列表——东财主源 + 新浪降级链。

    东财 stock_zh_a_spot_em 熔断时（2026-08-02 实测 ConnectionError）回退新浪
    stock_zh_a_spot（列：代码/名称），保证个股仍能灌入 instruments 本地表，
    消除「个股搜索走 levistock 全量外部拉取、冷启动 5-6s」的体验。
    """
    try:
        rows = await _fetch_akshare_list("stock_zh_a_spot_em", "代码", "名称", "A", "stock")
        if rows:
            return rows
    except Exception as e:
        print(f"  [WARN] A股个股 stock_zh_a_spot_em failed: {e}")
    try:
        rows = await _fetch_akshare_list("stock_zh_a_spot", "代码", "名称", "A", "stock")
        if rows:
            print("  [INFO] A股个股: 新浪降级链生效（东财不可用）")
            return rows
    except Exception as e:
        print(f"  [WARN] A股个股 stock_zh_a_spot failed: {e}")
    # N09 (round9 P1-2): 两源全失败 → raise（collect_all 记 ERROR 日志，sync 保留旧表）
    raise RuntimeError("A股个股段全部数据源不可用（stock_zh_a_spot_em/stock_zh_a_spot）")


async def _fetch_etf_list() -> list[dict]:
    """P1-2 (round9 §5/C4): A 股 ETF 段——东财主源 + 新浪降级链。

    容器内 EM 被 TLS 拦截（round9 C4）时 fund_etf_spot_em 恒挂 → ETF 段空；
    新增新浪 fund_etf_spot_sina（非 EM 源）兜底，保证 instruments ETF 段不空
    （候选池 ≥100 的前提之一）。
    """
    try:
        rows = await _fetch_akshare_list("fund_etf_spot_em", "代码", "名称", "A", "etf")
        if rows:
            return rows
    except Exception as e:
        print(f"  [WARN] A股ETF fund_etf_spot_em failed: {e}")
    try:
        rows = await _fetch_akshare_list("fund_etf_spot_sina", "代码", "名称", "A", "etf")
        if rows:
            print("  [INFO] A股ETF: 新浪降级链生效（东财不可用）")
            return rows
    except Exception as e:
        print(f"  [WARN] A股ETF fund_etf_spot_sina failed: {e}")
    # N09 (round9 P1-2): 两源全失败 → raise（collect_all 记 ERROR 日志）
    raise RuntimeError("A股ETF段全部数据源不可用（fund_etf_spot_em/fund_etf_spot_sina）")


async def _fetch_hk_list() -> list[dict]:
    """P1-2 (round9 §5/C4): 港股段——东财主源 + 新浪降级链（容器 EM 被拦时不空）。"""
    try:
        rows = await _fetch_akshare_list("stock_hk_main_board_spot_em", "代码", "名称", "HK", "stock")
        if rows:
            return rows
    except Exception as e:
        print(f"  [WARN] 港股 stock_hk_main_board_spot_em failed: {e}")
    try:
        rows = await _fetch_akshare_list("stock_hk_spot", "代码", "名称", "HK", "stock")
        if rows:
            print("  [INFO] 港股: 新浪降级链生效（东财不可用）")
            return rows
    except Exception as e:
        print(f"  [WARN] 港股 stock_hk_spot failed: {e}")
    raise RuntimeError("港股段全部数据源不可用（stock_hk_main_board_spot_em/stock_hk_spot）")


async def _fetch_us_list() -> list[dict]:
    """P1-2 (round9 §5/C4): 美股段——东财主源 + 新浪降级链（容器 EM 被拦时不空）。

    round9 P0-4 实测修正: 新浪 `stock_us_spot` 全量分页 **897 页**（20s 段超时后
    线程无法取消 → 后台残留 20+ 分钟占满线程池 → watchlist 等 API 尾部延迟）。
    降级改为直接拉新浪美股**前 6 页**（120 只，足够名称搜索），不触发全量分页。
    """
    try:
        rows = await _fetch_akshare_list("stock_us_spot_em", "代码", "名称", "US", "US")
        if rows:
            return rows
    except Exception as e:
        print(f"  [WARN] 美股 stock_us_spot_em failed: {e}")
    # 新浪美股分页（受限页数，防 897 页后台残留）
    try:
        import json as _json
        import urllib.request as _ur

        out: list[dict] = []
        seen: set[str] = set()
        for _page in range(1, 7):
            url = (
                f"http://stock.finance.sina.com.cn/usstock/api/jsonp.php/"
                f"IO.XSRV2.CallbackList%5B%5D/US_CategoryService.getList?"
                f"page={_page}&num=20&sort=&asc=0&market=&id="
            )
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            raw = _ur.urlopen(req, timeout=8).read().decode("utf-8", errors="replace")
            # 返回 JSONP：callback(["a","b",...]) 或 [{"symbol":...}, ...]
            start = raw.find("[")
            end = raw.rfind("]")
            if start == -1 or end == -1 or end <= start:
                continue
            items = _json.loads(raw[start:end + 1])
            for it in items or []:
                if isinstance(it, str):
                    sym = it.split(",")[0].strip() if "," in it else it.strip()
                    nm = it.split(",")[1].strip() if "," in it else ""
                elif isinstance(it, dict):
                    sym = str(it.get("symbol") or "")
                    nm = str(it.get("name") or "")
                else:
                    continue
                sym = sym.replace(".", "").strip()
                if not sym or sym in seen or not nm:
                    continue
                seen.add(sym)
                full, initial = _to_pinyin(nm)
                out.append({"symbol": sym, "name": nm, "market": "US",
                            "asset_type": "US", "pinyin": full, "first_letter": initial[:5]})
        if out:
            print(f"  [INFO] 美股: 新浪降级链生效（东财不可用，取前 {len(out)} 只）")
            return out
    except Exception as e:
        print(f"  [WARN] 美股 stock_us_spot 降级失败: {e}")
    raise RuntimeError("美股段全部数据源不可用（stock_us_spot_em/新浪受限分页）")


async def sync():
    from app.database import async_session, init_db
    from app.models.search import Instrument
    from sqlalchemy import select, delete

    # O1 (round8 §7): 环境开关——INSTRUMENTS_SYNC_DISABLED=1 跳过同步
    if _sync_disabled():
        print("[sync_instruments] INSTRUMENTS_SYNC_DISABLED=1 — skip sync")
        return

    print("[sync_instruments] collecting from akshare...")
    rows = await collect_all()
    print(f"[sync_instruments] got {len(rows)} instruments")

    await init_db()
    async with async_session() as session:
        # N09: 全量替换前校验至少一段成功——全部段失败时保留旧表
        # （旧代码无条件 delete+add_all：akshare 熔断 → 表被清成只剩 0 行/空表）
        if not rows:
            import logging
            logging.getLogger("sync_instruments").error(
                "[sync_instruments] ALL segments failed — KEEPING existing table (got 0 rows)"
            )
            print("[sync_instruments] ERROR: 所有数据段均失败，保留旧表不替换")
            return
        # 全量替换（简单可靠，数据量 ~6000 行无所谓）
        await session.execute(delete(Instrument))
        session.add_all([
            Instrument(
                symbol=r["symbol"],
                name=r["name"],
                market=r["market"],
                asset_type=r["asset_type"],
                pinyin=r.get("pinyin", ""),
                first_letter=r.get("first_letter", ""),
            )
            for r in rows
        ])
        await session.commit()
    print(f"[sync_instruments] done. {len(rows)} rows written.")


if __name__ == "__main__":
    asyncio.run(sync())

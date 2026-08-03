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
import sys
from pathlib import Path

# 让脚本能 import app
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

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
    """通用 akshare 列表拉取 + 归一化为 instruments 行。"""
    import akshare as ak
    try:
        df = getattr(ak, fn_name)()
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

    每段（A 股个股 / ETF / 港股）独立统计行数；失败段打 ERROR 而非仅 WARN。
    """
    import logging
    logger = logging.getLogger("sync_instruments")
    segments = [
        ("A股个股", "stock_zh_a_spot_em"),
        ("A股ETF", "fund_etf_spot_em"),
        ("港股", "stock_hk_main_board_spot_em"),
    ]
    tasks = [
        (_fetch_a_stock_list() if fn == "stock_zh_a_spot_em"
         else _fetch_akshare_list(fn, "代码", "名称", mkt, at))
        for (_, fn), (mkt, at) in zip(segments, [("A", "stock"), ("A", "etf"), ("HK", "stock")])
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
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
    return []


async def sync():
    from app.database import async_session, init_db
    from app.models.search import Instrument
    from sqlalchemy import select, delete

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

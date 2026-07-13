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
        from app.fetchers.akshare_fetcher import _decode_df
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
    tasks = [
        _fetch_akshare_list("stock_zh_a_spot_em", "代码", "名称", "A", "stock"),
        _fetch_akshare_list("fund_etf_spot_em", "代码", "名称", "A", "etf"),
        _fetch_akshare_list("stock_hk_main_board_spot_em", "代码", "名称", "HK", "stock"),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    merged: list[dict] = []
    seen = set()
    for res in results:
        if isinstance(res, Exception):
            print(f"  [WARN] gather error: {res}")
            continue
        for row in res:
            key = (row["symbol"], row["market"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


async def sync():
    from app.database import async_session, init_db
    from app.models.search import Instrument
    from sqlalchemy import select, delete

    print("[sync_instruments] collecting from akshare...")
    rows = await collect_all()
    print(f"[sync_instruments] got {len(rows)} instruments")

    await init_db()
    async with async_session() as session:
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

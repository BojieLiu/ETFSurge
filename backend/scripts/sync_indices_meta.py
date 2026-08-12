"""同步指数元数据到 indices_meta 表（供搜索/下拉/分析入口）。

数据源（按优先级）：
1. 新浪 A 股指数: ak.stock_zh_index_spot_sina()        -> 562 个
2. 新浪港股指数: ak.stock_hk_index_spot_sina()        -> ~38 个
3. 同花顺行业指数: ak.stock_board_industry_index_ths() -> ~600 个
4. 同花顺概念指数: ak.stock_board_concept_index_ths()  -> ~600 个

运行: python -m scripts.sync_indices_meta
"""

import asyncio
import sys
from pathlib import Path

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


async def _fetch_sina_a_indices():
    """抓取新浪 A 股指数（代码、名称）。"""
    import akshare as ak
    try:
        df = ak.stock_zh_index_spot_sina()
    except Exception as e:
        print(f"  [WARN] stock_zh_index_spot_sina failed: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        return []
    # 解码中文列
    try:
        from app.utils.decode import decode_df
        df = decode_df(df)
    except Exception:
        pass
    out = []
    for _, r in df.iterrows():
        code = str(r.get("代码", "") or r.get("symbol", "")).strip()
        name = str(r.get("名称", "") or r.get("name", "")).strip()
        if code and name:
            out.append({
                "symbol": code,
                "name": name,
                "market": "A",
                "category": "broad",
                "index_type": "price",
                "source": "sina",
            })
    return out


async def _fetch_sina_hk_indices():
    """抓取新浪港股指数。"""
    import akshare as ak
    try:
        df = ak.stock_hk_index_spot_sina()
    except Exception as e:
        print(f"  [WARN] stock_hk_index_spot_sina failed: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, r in df.iterrows():
        code = str(r.get("代码", "") or r.get("symbol", "")).strip()
        name = str(r.get("名称", "") or r.get("name", "")).strip()
        if code and name:
            out.append({
                "symbol": code,
                "name": name,
                "market": "HK",
                "category": "broad",
                "index_type": "price",
                "source": "sina",
            })
    return out


async def _fetch_ths_industry_indices():
    """抓取同花顺行业指数。"""
    import akshare as ak
    try:
        df = ak.stock_board_industry_index_ths()
    except Exception as e:
        print(f"  [WARN] stock_board_industry_index_ths failed: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, r in df.iterrows():
        code = str(r.get("指数代码", "") or r.get("代码", "") or r.get("symbol", "")).strip()
        name = str(r.get("指数名称", "") or r.get("名称", "") or r.get("name", "")).strip()
        if code and name:
            out.append({
                "symbol": code,
                "name": name,
                "market": "A",
                "category": "industry",
                "index_type": "price",
                "source": "ths",
            })
    return out


async def _fetch_ths_concept_indices():
    """抓取同花顺概念指数。"""
    import akshare as ak
    try:
        df = ak.stock_board_concept_index_ths()
    except Exception as e:
        print(f"  [WARN] stock_board_concept_index_ths failed: {e}")
        return []
    if df is None or getattr(df, "empty", True):
        return []
    out = []
    for _, r in df.iterrows():
        code = str(r.get("指数代码", "") or r.get("代码", "") or r.get("symbol", "")).strip()
        name = str(r.get("指数名称", "") or r.get("名称", "") or r.get("name", "")).strip()
        if code and name:
            out.append({
                "symbol": code,
                "name": name,
                "market": "A",
                "category": "concept",
                "index_type": "price",
                "source": "ths",
            })
    return out


# P0-20/P0-22 (round16 3.21/3.24): 静态兜底指数段——「恒生港股通」系列 + 主流
# 港股指数 + 美股主流指数。数据源失败/未接入时仍保证入表（搜索/分析入口可用）。
_STATIC_EXTRA_INDICES: list[dict] = [
    # ── 恒生港股通系列（中证指数官网/东财指数列表真实存在） ──
    {"symbol": "H11146", "name": "恒生港股通中国内地银行指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "H11145", "name": "恒生港股通高股息率指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "H11141", "name": "恒生港股通央企指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "H11144", "name": "恒生港股通科技指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "H11142", "name": "恒生港股通中国内地100指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "H11143", "name": "恒生港股通医疗保健指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    # ── 主流港股指数补充（恒生家族 + 港股通宽基） ──
    {"symbol": "HSI", "name": "恒生指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "HSCEI", "name": "恒生中国企业指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "HSTECH", "name": "恒生科技指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "HSCCI", "name": "恒生中国内地地产指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "CES100", "name": "中证港股通精选100指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    # ── 美股主流指数（P0-22：US tab 指数搜索） ──
    {"symbol": "SPX", "name": "标普500指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "SPY", "name": "SPDR标普500ETF", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "DJI", "name": "道琼斯工业平均指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "IXIC", "name": "纳斯达克综合指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "NDX", "name": "纳斯达克100指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "VIX", "name": "CBOE波动率指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "RUT", "name": "罗素2000指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
]


async def collect_all() -> list[dict]:
    print("[sync_indices_meta] collecting from all sources...")
    tasks = [
        _fetch_sina_a_indices(),
        _fetch_sina_hk_indices(),
        _fetch_ths_industry_indices(),
        _fetch_ths_concept_indices(),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    merged = []
    seen = set()
    for res in results:
        if not isinstance(res, (list, tuple)):
            print(f"  [WARN] gather error: {res}")
            continue
        for item in res:
            key = (item["symbol"], item["market"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    # P0-20/P0-22 (round16 3.21/3.24): 静态兜底段——「恒生港股通」系列与主流
    # 港股/美股指数（SPX/道琼斯/纳斯达克等）。新浪港股指数仅 ~38 条且恒缺
    # 「恒生港股通」系列；美股段数据源从未接入。静态段保证这些指数必然入表
    # （不依赖外部源状态），搜索/分析入口可用。
    for _s in _STATIC_EXTRA_INDICES:
        key = (_s["symbol"], _s["market"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(_s)
    print(f"[sync_indices_meta] collected {len(merged)} indices")
    return merged


async def sync():
    from app.database import async_session, init_db
    from app.models.search import IndexMeta
    from sqlalchemy import delete

    rows = await collect_all()
    if not rows:
        print("[sync_indices_meta] no data collected, abort")
        return

    # 补全拼音
    for r in rows:
        if "pinyin" not in r:
            r["pinyin"], r["first_letter"] = _to_pinyin(r["name"])

    await init_db()
    async with async_session() as session:
        # 全量替换（数据量 ~2000 行，简单可靠）
        await session.execute(delete(IndexMeta))
        session.add_all([
            IndexMeta(
                symbol=r["symbol"],
                name=r["name"],
                market=r["market"],
                category=r["category"],
                index_type=r["index_type"],
                source=r["source"],
                pinyin=r.get("pinyin", ""),
                first_letter=r.get("first_letter", ""),
            )
            for r in rows
        ])
        await session.commit()
    print(f"[sync_indices_meta] done. {len(rows)} rows written.")


if __name__ == "__main__":
    asyncio.run(sync())
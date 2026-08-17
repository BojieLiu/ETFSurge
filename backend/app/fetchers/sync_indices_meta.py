"""同步指数元数据到 indices_meta 表（供搜索/下拉/分析入口）。

数据源（按优先级）：
1. 新浪 A 股指数: ak.stock_zh_index_spot_sina()        -> 562 个
2. 新浪港股指数: ak.stock_hk_index_spot_sina()        -> ~38 个
3. 同花顺行业指数: ak.stock_board_industry_index_ths() -> ~600 个
4. 同花顺概念指数: ak.stock_board_concept_index_ths()  -> ~600 个

round25 R30: 本模块自 `scripts/` 移入 `app/fetchers/`——scripts/ 被 .dockerignore 排除
出镜像导致容器内启动同步 `No module named 'scripts'` 静默失败；移入 app 包后容器内可
正常 import。运行:
  python -m app.fetchers.sync_indices_meta
"""

import asyncio

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
    """抓取新浪 A 股指数（代码、名称）。

    round25 R30 附带: akshare 为同步调用——经 asyncio.to_thread 提交线程池，
    避免阻塞事件循环（audit_async_blocking 门禁，async def ≠ 非阻塞铁律）。
    """
    import asyncio
    import akshare as ak
    try:
        df = await asyncio.to_thread(ak.stock_zh_index_spot_sina)
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
    import asyncio
    import akshare as ak
    try:
        df = await asyncio.to_thread(ak.stock_hk_index_spot_sina)
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
    import asyncio
    import akshare as ak
    try:
        df = await asyncio.to_thread(ak.stock_board_industry_index_ths)
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
    import asyncio
    import akshare as ak
    try:
        df = await asyncio.to_thread(ak.stock_board_concept_index_ths)
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
    # ── round19 P8-① (2026-08-12): 恒生行业/综合指数静态段扩展——新浪源 ~38 条
    # 无行业/主题细分；恒生行业分类（金融/地产/公用/工商）+ 综合行业 10 项 +
    # 主题指数。symbol 以腾讯 hk{sym} K 线可拉验证（HSCI/HSF 已实测 320 根）。
    # HSAHC（恒生医疗保健）腾讯不覆盖，仍入表供搜索（行情层标注「暂无行情」）。
    {"symbol": "HSCI", "name": "恒生综合指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "HSF", "name": "恒生金融分类指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSP", "name": "恒生地产分类指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSU", "name": "恒生公用事业分类指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSC", "name": "恒生工商业分类指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIE", "name": "恒生综合能源业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIM", "name": "恒生综合原材料业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCII", "name": "恒生综合工业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCICD", "name": "恒生综合非必需性消费业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCICS", "name": "恒生综合必需性消费业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIH", "name": "恒生综合医疗保健业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIF", "name": "恒生综合金融业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIPC", "name": "恒生综合地产建筑业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIT", "name": "恒生综合资讯科技业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSCIC", "name": "恒生综合企业指数", "market": "HK", "category": "industry", "index_type": "price", "source": "static"},
    {"symbol": "HSAHC", "name": "恒生医疗保健指数", "market": "HK", "category": "theme", "index_type": "price", "source": "static"},
    {"symbol": "HSII", "name": "恒生互联网科技业指数", "market": "HK", "category": "theme", "index_type": "price", "source": "static"},
    {"symbol": "HSHYLDI", "name": "恒生高股息率指数", "market": "HK", "category": "theme", "index_type": "price", "source": "static"},
    {"symbol": "HSHKBIO", "name": "恒生香港上市生物科技指数", "market": "HK", "category": "theme", "index_type": "price", "source": "static"},
    # ── 美股主流指数（P0-22：US tab 指数搜索） ──
    {"symbol": "SPX", "name": "标普500指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "DJI", "name": "道琼斯工业平均指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "IXIC", "name": "纳斯达克综合指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "NDX", "name": "纳斯达克100指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "VIX", "name": "CBOE波动率指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "RUT", "name": "罗素2000指数", "market": "US", "category": "broad", "index_type": "price", "source": "static"},
    # ── round26 Q4/Q6: 美股指数索引补全（旧表仅 7 条，费城/SOX 等搜不到） ──
    # 注: iShares半导体ETF(SOXX)/SPDR材料ETF(XLB) 为 ETF，非指数——移出指数种子表，
    # 改入 market_service.HKUS_ETF_MAP（个股/ETF tab 命中），避免 index_type 伪装成指数。
    {"symbol": "SOX", "name": "费城半导体指数", "market": "US", "category": "theme", "index_type": "price", "source": "static"},
    # 彭博代码 ^GSPC/^DJI/^IXIC 与 SPX/DJI/IXIC 重复，仅后缀不同——删除避免重复命中。
    # ── round26 Q4: 恒生港股通「低波动」变体 + 主题补充（旧表恒缺该变体） ──
    {"symbol": "H11148", "name": "恒生港股通高股息低波动指数", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "H11149", "name": "恒生港股通高股息低波动指数(HKD)", "market": "HK", "category": "broad", "index_type": "price", "source": "static"},
    {"symbol": "HSHLDI", "name": "恒生港股通低波幅指数", "market": "HK", "category": "theme", "index_type": "price", "source": "static"},
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
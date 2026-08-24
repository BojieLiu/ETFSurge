"""FM3/FM4 前置探针（docs/round35-architecture-review.md §15.5，D1 纪律）。

三个数据可用性探针，决定 etf_quality 第五顶层键能否进实施清单：
  A. IOPV 链（premium_discount 输入）：_fetch_iopv_chain 命中率 + 折溢价分布
     区分度（std / 非零占比）——全池同涨同跌的常数因子无选基价值。
  B. benchmark_close（tracking_error 输入）：_WIDE_BASIS_INDEX_CODES 对候选池
     的覆盖率 + 抽样实拉指数历史确认 closes 可得。
  C. shares_change_20d：fetch_etf_shares_outstanding 返回结构实测——round9 P1-9
     结论「份额历史无免费公开源」是否仍成立。

探测克制（设计流程 D1）：单遍执行、无重试循环；外部调用全部带超时；
结果标注交易窗口（盘后跑出的 IOPV/折溢价数字打「待交易时段复测」标）。

用法：cd backend && python scripts/probe_fm3_data_availability.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# 候选池代表样本：宽基/行业/主题/商品/债券 各取常见锚与活跃品种
SAMPLE_SYMBOLS = [
    "510300",  # 沪深300ETF（核心锚）
    "510500",  # 中证500ETF
    "159338",  # 中证A500ETF（第二锚）
    "512890",  # 红利低波
    "512100",  # 中证1000
    "513050",  # 中概互联（跨境/QDII）
    "518880",  # 黄金ETF（防御锚）
    "512480",  # 半导体
]

TRADING_WINDOWS = (("09:30", "11:30"), ("13:00", "15:00"))


def trading_window_now() -> tuple[bool, str]:
    now = datetime.now()
    if now.weekday() >= 5:
        return False, f"weekend({now:%a})"
    t = now.strftime("%H:%M")
    for lo, hi in TRADING_WINDOWS:
        if lo <= t <= hi:
            return True, f"in-window({t})"
    return False, f"off-hours({t})"


async def probe_iopv_chain() -> dict:
    """探针 A：IOPV 链命中率 + 折溢价分布区分度。"""
    from app.factors.factor_registry import _fetch_iopv_chain, _iopv_sina_symbols

    s_list = _iopv_sina_symbols(SAMPLE_SYMBOLS)
    data, source = await _fetch_iopv_chain(s_list, SAMPLE_SYMBOLS)
    premiums: dict[str, float] = {}
    missing = []
    for sym in SAMPLE_SYMBOLS:
        # 链返回 key 带 sh/sz 前缀，归一化回裸代码
        hit = next((v for k, v in data.items() if k.endswith(sym)), None)
        if not hit or not hit.get("nav"):
            missing.append(sym)
            continue
        price, nav = hit.get("price") or 0.0, hit["nav"]
        if price > 0 and nav > 0:
            premiums[sym] = (price - nav) / nav
    vals = list(premiums.values())
    distinct = bool(vals) and len(vals) >= 3 and statistics.pstdev(vals) > 5e-4
    nonzero_ratio = (sum(1 for v in vals if abs(v) > 1e-6) / len(vals)) if vals else 0.0
    return {
        "probe": "A_iopv_chain",
        "source": source,
        "hit": len(premiums),
        "total": len(SAMPLE_SYMBOLS),
        "missing": missing,
        "premiums": {k: round(v, 6) for k, v in premiums.items()},
        "pstdev": round(statistics.pstdev(vals), 6) if vals else None,
        "nonzero_ratio": round(nonzero_ratio, 3),
        "distinct_enough": distinct and nonzero_ratio >= 0.3,
    }


async def probe_benchmark_close() -> dict:
    """探针 B：基准映射覆盖率 + 抽样实拉指数历史。"""
    from app.services.hub._kline import KlineMixin
    from app.services.market_data_hub import market_data_hub as hub

    mapping = KlineMixin._WIDE_BASIS_INDEX_CODES or {}
    covered = [s for s in SAMPLE_SYMBOLS if mapping.get(s)]
    uncovered = [s for s in SAMPLE_SYMBOLS if not mapping.get(s)]

    sampled: dict[str, dict] = {}
    for sym in covered[:2]:  # 克制：最多实拉 2 只
        idx = mapping[sym]
        try:
            hist = await asyncio.wait_for(
                hub.get_market_history(idx, "index", "daily"), timeout=12,
            )
            # 双方言：系统格式中文键（收盘）或英文键 close
            closes = []
            for r in (hist or []):
                c = r.get("close") or r.get("收盘")
                if c:
                    try:
                        closes.append(float(c))
                    except (TypeError, ValueError):
                        continue
            sampled[sym] = {
                "index": idx,
                "closes_len": len(closes),
                "usable": len(closes) >= 20,
                "last_close": closes[-1] if closes else None,
            }
        except Exception as e:
            sampled[sym] = {"index": idx, "error": str(e)[:120]}
    return {
        "probe": "B_benchmark_close",
        "mapping_size": len(mapping),
        "covered": covered,
        "uncovered": uncovered,
        "coverage_ratio": round(len(covered) / len(SAMPLE_SYMBOLS), 3),
        "sampled": sampled,
        "usable": (
            len(covered) >= 4
            and all(v.get("usable") for v in sampled.values() if v)
        ),
    }


async def probe_shares_change() -> dict:
    """探针 C：份额变化率数据源现状复核。"""
    from app.fetchers.china_market import fetch_etf_shares_outstanding

    results = {}
    any_change = False
    for sym in SAMPLE_SYMBOLS[:2]:  # 克制：2 只（akshare 全量缓存共享）
        try:
            r = await asyncio.wait_for(
                asyncio.to_thread(fetch_etf_shares_outstanding, sym), timeout=25,
            )
        except Exception as e:
            r = {"error": str(e)[:120]}
        results[sym] = r
        if isinstance(r, dict) and r.get("shares_change_20d") is not None:
            any_change = True
    return {
        "probe": "C_shares_change",
        "results": results,
        "history_available": any_change,
    }


async def main() -> int:
    in_window, win_desc = trading_window_now()
    print(f"[probe] trading window: {win_desc} "
          f"{'(结果有效)' if in_window else '(盘后——IOPV/折溢价数字待交易时段复测)'}")
    out: dict = {"as_of": datetime.now().isoformat(timespec="seconds"),
                 "window": win_desc, "in_window": in_window}

    try:
        out["A"] = await probe_iopv_chain()
    except Exception as e:
        out["A"] = {"probe": "A_iopv_chain", "error": str(e)[:200]}
    print(json.dumps(out["A"], ensure_ascii=False))

    try:
        out["B"] = await probe_benchmark_close()
    except Exception as e:
        out["B"] = {"probe": "B_benchmark_close", "error": str(e)[:200]}
    print(json.dumps(out["B"], ensure_ascii=False))

    await asyncio.sleep(60)  # 探测间隔 ≥60s（D1 克制纪律）
    try:
        out["C"] = await probe_shares_change()
    except Exception as e:
        out["C"] = {"probe": "C_shares_change", "error": str(e)[:200]}
    print(json.dumps(out["C"], ensure_ascii=False))

    dest = Path(__file__).parent / "probe_fm3_results.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] saved -> {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

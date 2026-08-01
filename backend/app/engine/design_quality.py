# -*- coding: utf-8 -*-
"""T14: 方案质量门禁纯函数（§8.5.3 清单自动化）。

validate_design_quality(strategies) -> list[str]：返回质量问题列表，空 = 通过。
清单：① 核心层 ≥1 主流宽基；② 卫星层同板块 ≤2；③ RSI 值域（全<3/全>97 视为错误）；
④ 信号方向与因子分自洽（技术<0 且 估值<0 → 信号不得为 buy/加仓）。
⑤（三方案差异）由调用方对多方案整体比较（见 check_strategies_differ）。
"""
from collections import Counter

# §9.6 宽基清单（与 etf_scanner.WIDE_BASIS_STATIC 一致）
WIDE_BASIS = {"510300", "510500", "510050", "588000", "159915", "510880"}

# 信号类词汇（正向）
_BULLISH_SIGNALS = {"buy", "买入", "加仓", "看多", "偏多"}


def _normalize_segment(text: str) -> str:
    """板块/概念段归一化（同板块识别用）。"""
    t = (text or "").strip()
    for w in ("ETF", "指数", "LOF"):
        t = t.replace(w, "")
    return t


def validate_design_quality(strategies: list[dict]) -> list[str]:
    """对方案列表执行 §8.5.3 质量门禁，返回问题列表（空 = 通过）。"""
    issues: list[str] = []
    for s in strategies:
        sid = s.get("id") or s.get("risk_profile") or "?"
        etfs = [a for a in s.get("etfs", []) if a.get("symbol") != "CASH"]
        core = [a for a in etfs if a.get("layer") == "core"]
        sats = [a for a in etfs if a.get("layer") == "satellite"]

        # ① 核心层 ≥1 只主流宽基
        if not any(a.get("symbol") in WIDE_BASIS for a in core):
            issues.append(f"{sid}: 核心层无主流宽基")

        # ② 卫星层同板块 ≤2 只（按 tracked_index/segment/name 归一化）
        seg_counts: Counter = Counter()
        for a in sats:
            seg = _normalize_segment(
                a.get("tracked_index") or a.get("segment") or a.get("name", "")
            )
            if seg:
                seg_counts[seg] += 1
        for seg, cnt in seg_counts.items():
            if cnt > 2:
                issues.append(f"{sid}: 卫星层板块「{seg}」有 {cnt} 只（>2）")

        # ③ RSI 值域（全 <3 或全 >97 视为数据错误）
        rsi_vals = [
            float(a.get("factor_scores", {}).get("technical.rsi.rsi_14"))
            for a in etfs
            if a.get("factor_scores", {}).get("technical.rsi.rsi_14") is not None
        ]
        if rsi_vals and all(v < 3 for v in rsi_vals):
            issues.append(f"{sid}: RSI 全部 <3（数据错误）")
        if rsi_vals and all(v > 97 for v in rsi_vals):
            issues.append(f"{sid}: RSI 全部 >97（数据错误）")

        # ④ 信号方向与因子分自洽（技术<0 且 估值<0 → 不得正向）
        for a in etfs:
            fs = a.get("factor_scores") or {}
            sig = str(a.get("signal") or "").lower()
            t_val = fs.get("technical")
            v_val = fs.get("valuation")
            if (
                isinstance(t_val, (int, float)) and isinstance(v_val, (int, float))
                and t_val < 0 and v_val < 0
                and sig in _BULLISH_SIGNALS
            ):
                issues.append(f"{sid}: {a.get('symbol')} 技术/估值双弱仍判多")

    return issues


def check_strategies_differ(strategies: list[dict]) -> bool:
    """⑤ 三套方案差异非仅权重+现金机械缩放：至少两套的层权重结构不同。"""
    sigs: set[tuple] = set()
    for s in strategies:
        etfs = [a for a in s.get("etfs", []) if a.get("symbol") != "CASH"]
        core_w = sum(a.get("weight", 0) for a in etfs if a.get("layer") == "core")
        sat_w = sum(a.get("weight", 0) for a in etfs if a.get("layer") == "satellite")
        def_w = sum(a.get("weight", 0) for a in etfs if a.get("layer") == "defense")
        sigs.add((round(core_w, 3), round(sat_w, 3), round(def_w, 3)))
    return len(sigs) >= 2

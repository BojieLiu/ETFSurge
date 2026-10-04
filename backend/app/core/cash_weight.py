"""现金仓位（CASH 行）口径唯一事实源。

**为什么需要这个模块**：现金在本管线里不是一个标量字段，而是
`strategies[].allocations[]`（渲染层）/ `strategies[].etfs[]`（编排层）内
一行 `symbol == "CASH"` / `layer == "cash"` 的合成行——由
`app/services/strategy_design.py` 追加（口径见「权重不归一化」约定：
`cash = 1 - Σ非现金权重`，**不按权重和归一化**）。

因此任何「按 layer 过滤」的消费者都会把它整体丢掉。历史缺口：报告 §一
`资产结构` 行只印三层（核心 45% + 卫星 20% + 防御 10% = 75%）、明细表
`continue` 掉 CASH 行，而方案卡片是齐的（header 现金 25% + 明细 CASH 行）。
本模块把口径收敛到一处，供报告渲染层与编排层共用。

纯函数、无 I/O、无外部依赖（与 `app/engine/` 同样的纯度要求）。
"""

from __future__ import annotations

CASH_SYMBOL = "CASH"


def _num(v):
    """安全数值化：None / str / 非数值 → None（对齐 design_report._pct_num 的 round23 遗留修复）。"""
    if v is None or isinstance(v, bool) or isinstance(v, str):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cash_weight_of(strategy: dict) -> float | None:
    """返回方案现金仓位（小数口径，如 ``0.25``）。

    取值优先级：
    1. **引擎 CASH 行**（权威，与方案卡片同源）；
    2. 无 CASH 行时按 ``residual = 1 - Σ非现金权重`` 推导——与前端
       `DesignResult.displayAllocations` 的合成口径一致（残余现金 > 0.5% 才补行）；
    3. 方案无任何权重数据 → ``None``，调用方须渲染「—」，**不得编造百分比**
       （旧报告实现 ``... if cash else 10`` 会在此处凭空造出 10% 现金）；
    4. 无 CASH 行且**某个非现金权重不可解析**（非数值）→ ``None``。此时若把该
       权重当 0 求和会推导出「现金 100%」的假满仓现金；宁可缺数据也不造数。
       （实测各写入点均为数值：strategy_design.py:199/215/688/1293/1393，
       故此分支是防御性的。）

    结果夹到 ``>= 0``：Σ非现金 > 1（超额配仓）时残余现金为负，与引擎口径
    （`_reconcile_after_enforce` 把现金行归零而非置负）对齐。
    """
    allocs = strategy.get("allocations") or strategy.get("etfs") or []
    rows = [e for e in allocs if isinstance(e, dict)]
    if not rows:
        return None
    cash = next((e for e in rows if e.get("symbol") == CASH_SYMBOL), None)
    if cash is not None:
        return max(0.0, _num(cash.get("weight") or cash.get("target_weight") or 0) or 0.0)
    non_cash = 0.0
    for e in rows:
        if e.get("symbol") == CASH_SYMBOL:
            continue
        w = _num(e.get("weight") or e.get("target_weight") or 0)
        if w is None:
            return None
        non_cash += w
    return max(0.0, round(1.0 - non_cash, 4))


def cash_row_of(strategy: dict) -> dict | None:
    """返回方案的引擎 CASH 行本身（无则 None）——供需要现金行理由/原始权重的调用方。"""
    allocs = strategy.get("allocations") or strategy.get("etfs") or []
    return next(
        (e for e in allocs if isinstance(e, dict) and e.get("symbol") == CASH_SYMBOL),
        None,
    )

"""FS1 (round35 §15.6): 因子值「有意义非零」单点判定。

背景（docs/round35-architecture-review.md §15.6-FS1）：零值阈值此前三处各自为政——
factor_registry 记账 abs>0.001 / factor_aggregate 聚合过滤 abs>0.001 /
ic_tracker 零值统计按因子特判 tracking_error=1e-6 其余 0.001；tracking_error 的
特判已证明该模式会复发（premium_discount 日常 ±0.1% 有被当占位零过滤的风险，
导致合法值被丢、IC 样本系统性偏少）。

本模块即单点：
- 新因子的合法零值容差只改 :data:`FACTOR_ZERO_TOLERANCE`；
- 各因子完整合法值域的权威描述在 factor_definitions.yaml（description 字段）
  与各 compute 函数注释——本表只管「多大算零」。
"""
from __future__ import annotations

#: 按因子覆盖的零值容差（abs(val) ≤ tol 视为占位零）。未列出的因子用默认。
FACTOR_ZERO_TOLERANCE: dict[str, float] = {
    # round14 P2-Z: tracking_error 合法区间 0.001~0.02——按 0.001 容差会把
    # 合法跟踪误差整段判零（有效样本 <3 → 永不产 IC），仅排除真 0。
    "etf.tracking_error": 1e-6,
    # FS1 复核（round35 §15.6 风险项落地，2026-08-24）：premium_discount 日常
    # ±0.1%（0.001）量级的合法折溢价曾被默认容差整体吞成「占位零」→ IC 样本
    # 系统性偏少。收紧到 2bp：占位 0.0 仍被滤（0.0 > 正容差不成立），≥3bp 的
    # 真实定价偏差进入样本；FM3 探针实测分布 pstdev≈2.1%，2bp 远低于信号尺度。
    "etf.premium_discount": 2e-4,
}

DEFAULT_ZERO_TOLERANCE = 0.001


def is_meaningful_value(code: str, val) -> bool:
    """判定因子值是否「有意义非零」（canonical 判定：abs(val) > tol，严格大于）。

    非数值（数据源异常可能给 str，R58）一律视为无意义。
    """
    if not isinstance(val, (int, float)):
        return False
    tol = FACTOR_ZERO_TOLERANCE.get(code, DEFAULT_ZERO_TOLERANCE)
    return abs(val) > tol

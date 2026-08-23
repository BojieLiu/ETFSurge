"""综合信号纯函数（round35 B1-F1b 从 analysis/signal.py 下沉）。

分层修复（docs/round35-architecture-review.md §4.1 D1）：engine/rationale.py 此前经
相对导入引用 app.analysis.signal，绕过了 check_engine_purity 的绝对前缀匹配——
引擎层真实依赖了上层 analysis 包。本模块把两个纯函数（_cap / composite_signal）
下沉至 engine 层；analysis/signal.py 头部 re-export 保持既有调用点兼容
（services→analysis→engine 为合法向下方向）。

同名陷阱：engine/composite_signal.py 是另一个模块（池层打分 compute_composite），
与本文件无关——下沉目标命名 signal.py 以避免语义混淆。
"""

from __future__ import annotations

from typing import Any


def _cap(v: float) -> float:
    """round24 R25: 单因子极端值封顶 |score| ≤ 1.0（composite_signal_with_gate
    降级分支也需复用，防单项拉平）。"""
    try:
        f = float(v or 0.0)
    except (TypeError, ValueError):
        f = 0.0
    return max(-1.0, min(1.0, f))


def composite_signal(
    technical: float = 0.0,
    valuation: float = 0.0,
    momentum: float = 0.0,
    weights: tuple[float, float, float] | None = None,
) -> dict[str, Any]:
    """F1-8/§9.7 R5: 三因子加权聚合综合信号（纯函数，无 I/O）。

    规则：
      - 聚合公式：0.4*技术 + 0.4*估值 + 0.2*动量（权重可覆盖）
      - 单因子极端值封顶 |score| ≤ 1.0，防单项拉平（如动量 +9 拉平技术/估值双弱）
      - 硬约束「技术<0 且 估值<0 → 综合信号不得为 buy/偏多，至多 hold」
        （589720 实测：技术 -0.408 / 估值 -0.462 曾因动量 +1.047 被误判偏多）

    Returns:
        {"signal": "buy"|"hold"|"sell", "score": float,
         "components": {"technical": t, "valuation": v, "momentum": m}}
    """
    t, v, m = _cap(technical), _cap(valuation), _cap(momentum)
    w = weights or (0.4, 0.4, 0.2)
    score = w[0] * t + w[1] * v + w[2] * m

    # 双弱不判多：技术/估值同时为负 → 至多 hold（动量不能拉平方向）
    if t < 0 and v < 0:
        score = min(score, 0.0)

    if score >= 0.5:
        signal = "buy"
    elif score <= -0.5:
        signal = "sell"
    else:
        signal = "hold"

    return {
        "signal": signal,
        "score": round(score, 3),
        "components": {"technical": t, "valuation": v, "momentum": m},
    }

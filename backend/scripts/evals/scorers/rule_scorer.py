"""规则轨 scorer（v7 §5.5 双轨评估之规则轨）。

四个 scorer，全部纯函数、可独立单测：
- score_quote:    数值/存在性比对（field_path 取值 + op 判定）
- score_format:   信封字段完整性（data/as_of/source/degraded）
- score_refusal:  拒答检测——无数据时输出必须声明缺失（零幻觉 = 100%）
- score_multi_step: 多步完成率（全部步 success + 最终步有输出）

判定值语义（统一三态）：
- "pass"  达标
- "fail"  不达标（阻断类）
- "error" 题目自身执行失败（工具异常），计 fail 但单独计数便于排查
"""
from __future__ import annotations

import re
from typing import Any


def _resolve_path(payload: Any, path: str) -> tuple[bool, Any]:
    """按 'data[0].price' 形式的 field_path 取值。返回 (found, value)。"""
    cur = payload
    for part in re.findall(r"[^\.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            idx = int(part[1:-1])
            if not isinstance(cur, list) or idx >= len(cur):
                return False, None
            cur = cur[idx]
        else:
            if not isinstance(cur, dict) or part not in cur:
                return False, None
            cur = cur[part]
    return True, cur


def score_quote(payload: dict, expect: dict) -> str:
    """行情题：op=present 字段存在即可；op=approx 数值容差比对。"""
    found, value = _resolve_path(payload, expect.get("field_path", ""))
    op = expect.get("op", "present")
    if op == "present":
        return "pass" if (found and value not in (None, "")) else "fail"
    if op == "approx":
        if not found or not isinstance(value, (int, float)):
            return "fail"
        want = float(expect["value"])
        tol = float(expect.get("tolerance", 0.01))
        return "pass" if abs(float(value) - want) <= tol else "fail"
    return "error"


def score_format(payload: dict, expect: dict) -> str:
    """格式题：信封四字段完整（data/as_of/source/degraded）——degraded 可 true。"""
    required = expect.get("fields", ["data", "as_of", "source", "degraded"])
    missing = [k for k in required if k not in payload]
    return "pass" if not missing else "fail"


def score_refusal(payload: dict, expect: dict) -> str:
    """拒答题：must_refuse=True 时期望 data 缺失且如实标注。
    - data=None + degraded=true -> pass（诚实缺失）
    - data=None + degraded=false -> fail（静默吞错）
    - data 有值 -> fail（期望拒答却有数据 = 编造风险）；strict=False 放行视为容错
    """
    must_refuse = expect.get("must_refuse", True)
    data = payload.get("data")
    degraded = bool(payload.get("degraded"))
    if must_refuse:
        if data is None:
            return "pass" if degraded else "fail"
        # data 有值：除非显式 strict=False（宽松口径），一律 fail
        if expect.get("strict", True) is False:
            return "pass"
        return "fail"
    return "pass" if data is not None else "fail"


def score_multi_step(payload: dict, expect: dict) -> str:
    """多步题：payload 为 RunReport dict——全部步无 error 且至少 1 步有输出。"""
    steps = payload.get("steps", [])
    if not steps:
        return "error"
    errored = [s for s in steps if s.get("error")]
    completed = [s for s in steps if s.get("output") is not None]
    need = int(expect.get("min_steps", len(steps)))
    if len(steps) < need:
        return "fail"
    return "pass" if not errored and completed else "fail"


_SCORERS = {
    "quote": score_quote,
    "factor": score_quote,      # 因子数值题与行情题同构（field_path + approx）
    "format": score_format,
    "refusal": score_refusal,
    "multi_step": score_multi_step,
}


def score_case(case_type: str, payload: dict, expect: dict) -> str:
    """按题型分发 scorer。未知题型 -> error。"""
    scorer = _SCORERS.get(case_type)
    if scorer is None:
        return "error"
    try:
        return scorer(payload, expect)
    except Exception:  # noqa: BLE001 - 单题评分异常不拖垮整批
        return "error"

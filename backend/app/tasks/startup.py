"""startup — warmup 计时/分段/预算告警纯函数（P2-3, docs/redundant-review.md §3 D6）。

冗余评审 D6 判定: main.py 1058+ 行 lifespan 聚合过多——warmup 计时/分段标签与
业务启动逻辑混排。本模块把「可单测的纯函数段」从 main.py 迁出：

- ``_WARMUP_SEQUENCE_LABELS`` / ``_WARMUP_SEGMENTS`` / ``_record_warmup_segment``
- ``_warmup_uncovered_segments`` / ``_format_warmup_budget_warning``
- ``_run_warmup_sequence``（串行编排，纯异步无 I/O 常量）

⚠️ main.py 保留同名 re-export（``from .tasks.startup import *`` 式显式清单）——
既有测试（test_warmup_sequence/test_warmup_two_phase 等）从 ``app.main`` 导入
这些符号，源码级守卫 ``main_mod.__file__`` 仍指向 main.py。后续批次再迁移
lifespan 内的 ``_warmup_*`` 协程族（需连带迁移 app.state 钩子，行为风险更高）。
"""
from __future__ import annotations

import logging
import time
from typing import Generator

logger = logging.getLogger(__name__)

# R170 (round52): sequence 7 段标签——budget 告警与 warmup_timing.json 同口径。
_WARMUP_SEQUENCE_LABELS: tuple[str, ...] = (
    "market_cache",
    "etf_cache",
    "global_indices",
    "sector_cache",
    "instruments_sync",
    "indices_meta_sync",
    "design_data",
)

_WARMUP_SEGMENTS: list[dict[str, object]] = []


def _record_warmup_segment(label: str, duration_s: float) -> None:
    """记录一个预热 sequence 分段的实测耗时（供 budget 告警归因）。"""
    _WARMUP_SEGMENTS.append({"label": label, "duration_ms": round(duration_s * 1000.0, 2)})


def _warmup_uncovered_segments(
    expected: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """返回「在 sequence 中但未留下分段计时」的段名（归属缺口自曝）。"""
    _expected = tuple(expected) if expected is not None else _WARMUP_SEQUENCE_LABELS
    _covered = {str(s["label"]) for s in _WARMUP_SEGMENTS}
    return [lb for lb in _expected if lb not in _covered]


def _format_warmup_budget_warning(
    elapsed: float,
    budget: float,
    segments: list[dict[str, object]],
    uncovered: list[str],
) -> str:
    """生成带归因信息的预热预算日志文案（纯函数，可单测）。"""
    def _ms(s: dict[str, object]) -> float:
        v = s.get("duration_ms")
        return float(v) if isinstance(v, (int, float)) else 0.0

    _top = sorted(segments, key=_ms, reverse=True)[:3]
    _parts: list[str] = []
    if _top:
        _parts.append(
            "分段 top3: "
            + "/".join(f"{s.get('label', '?')} {_ms(s) / 1000.0:.1f}s" for s in _top)
        )
    if uncovered:
        _parts.append("未入 timing 段: " + ",".join(uncovered))
    _attr = f"（{'; '.join(_parts)}）" if _parts else "（无分段计时数据）"
    if elapsed > budget:
        return (
            f"[warmup-budget] 预热总耗时 {elapsed:.1f}s 超过预算阈值 {budget:.1f}s，"
            f"可能存在回归{_attr}——见 logs/warmup_timing.json（PROFILE_WARMUP=1）"
        )
    return f"[warmup-budget] 预热总耗时 {elapsed:.1f}s（阈值 {budget:.1f}s，达标）"


async def _run_warmup_sequence(tasks: list) -> None:
    """O2 (round7 §7 P2): 预热任务串行执行——控并发峰值。

    旧实现 4 个重 IO 预热任务同时 create_task，各自内部并发 run_sync + 全量
    扫描 + akshare 分页叠加 → 预热高峰 shared_executor 64/64 饱和（P2 复现）。
    串行执行（前一个完成后启动下一个），内部并发上限不变；单个任务异常
    不阻断后续任务（预热失败静默，启动不阻塞）。

    R170 (round52): tasks 元素可为裸协程（向后兼容）或 ``(label, coro)``；带 label
    时记录分段耗时（无论任务成功/失败/超时——失败段同样要可归因）。
    """
    for _item in tasks:
        _label, _t = _item if isinstance(_item, tuple) else ("", _item)
        _t0 = time.time()
        try:
            await _t
        except Exception as e:  # noqa: BLE001
            logger.warning("[lifespan] warmup sequence step failed (non-fatal): %s", e)
        finally:
            if _label:
                _record_warmup_segment(_label, time.time() - _t0)

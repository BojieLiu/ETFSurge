"""
Warmup phase profiler for ETF Surge.

Captures function-level timing, cProfile stats, and pyinstrument traces
during the application warmup (lifespan) phase.

Usage:
    from ..profiling.warmup_profiler import WarmupProfiler, warmup_timer

    profiler = WarmupProfiler()
    with warmup_timer("init_db"):
        await init_db()
    profiler.enable_pyinstrument()
    ...
    profiler.disable_pyinstrument()
    profiler.write_report("warmup_report.json")
"""

import asyncio
import cProfile
import io
import json
import logging
import pstats
import time
import os
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger("profiler.warmup")


@dataclass
class TimingRecord:
    label: str
    duration_ms: float
    category: str = "general"
    note: str = ""


class WarmupProfiler:
    """Collects timing and profiling data during warmup."""

    def __init__(self, output_dir: str | None = None):
        self.records: list[TimingRecord] = []
        self._pyinstrument_session = None
        self._cprofile = cProfile.Profile()
        self._cprofile_active = False
        self._pyinstrument_active = False
        self._output_dir = output_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs"
        )
        os.makedirs(self._output_dir, exist_ok=True)

    def record(self, label: str, duration_ms: float, category: str = "general", note: str = ""):
        self.records.append(TimingRecord(label, duration_ms, category, note))

    def enable_cprofile(self):
        """Start cProfile CPU profiling."""
        if not self._cprofile_active:
            self._cprofile.enable()
            self._cprofile_active = True
            logger.info("[profiler] cProfile enabled")

    def disable_cprofile(self):
        """Stop cProfile CPU profiling."""
        if self._cprofile_active:
            self._cprofile.disable()
            self._cprofile_active = False
            self._save_cprofile_stats()
            logger.info("[profiler] cProfile disabled, stats saved")

    def enable_pyinstrument(self):
        """Start pyinstrument sampling profiler (async aware)."""
        if not self._pyinstrument_active:
            try:
                from pyinstrument import Profiler

                self._pyinstrument_session = Profiler(async_mode="disabled")
                self._pyinstrument_session.start()
                self._pyinstrument_active = True
                logger.info("[profiler] pyinstrument enabled")
            except ImportError:
                logger.warning("[profiler] pyinstrument not available, skipping")

    def disable_pyinstrument(self):
        """Stop pyinstrument and save HTML report."""
        if self._pyinstrument_active and self._pyinstrument_session:
            self._pyinstrument_session.stop()
            self._pyinstrument_active = False
            self._save_pyinstrument_report()
            logger.info("[profiler] pyinstrument disabled, report saved")

    def _save_cprofile_stats(self):
        """Dump cProfile stats as text + callers."""
        output_path = os.path.join(self._output_dir, "warmup_cprofile.txt")
        s = io.StringIO()
        ps = pstats.Stats(self._cprofile, stream=s).sort_stats("cumulative")
        ps.print_stats(60)
        ps.print_callees(30)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(s.getvalue())
        logger.info("[profiler] cProfile stats -> %s", output_path)

    def _save_pyinstrument_report(self):
        """Save pyinstrument report as HTML."""
        html_path = os.path.join(self._output_dir, "warmup_pyinstrument.html")
        try:
            html = self._pyinstrument_session.output_html()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            logger.info("[profiler] pyinstrument HTML -> %s", html_path)
        except Exception as e:
            logger.warning("[profiler] pyinstrument HTML save failed: %s", e)

        txt_path = os.path.join(self._output_dir, "warmup_pyinstrument.txt")
        try:
            txt = self._pyinstrument_session.output_text(unicode=True, color=False)
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(txt)
            logger.info("[profiler] pyinstrument text -> %s", txt_path)
        except Exception as e:
            logger.warning("[profiler] pyinstrument text save failed: %s", e)

    def write_report(self, filename: str = "warmup_timing.json") -> str:
        """Write structured timing report JSON."""
        path = os.path.join(self._output_dir, filename)
        report = {
            "total_duration_ms": sum(r.duration_ms for r in self.records),
            "records": [
                {
                    "label": r.label,
                    "duration_ms": round(r.duration_ms, 2),
                    "category": r.category,
                    "note": r.note,
                }
                for r in self.records
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info("[profiler] timing report -> %s", path)
        return path

    def print_summary(self):
        """Print a human-readable summary to logger."""
        total = sum(r.duration_ms for r in self.records)
        lines = [
            "=== Warmup Profiling Summary ===",
            f"{'Label':<50} {'ms':>10} {'Category':<20}",
            "-" * 80,
        ]
        for r in self.records:
            lines.append(f"{r.label:<50} {r.duration_ms:>8.1f}  {r.category:<20}")
        lines.append("-" * 80)
        lines.append(f"{'TOTAL':<50} {total:>8.1f}")
        lines.append("=" * 80)
        logger.info("\n".join(lines))


# Global profiler instance
_profiler: WarmupProfiler | None = None


def get_warmup_profiler() -> WarmupProfiler:
    global _profiler
    if _profiler is None:
        _profiler = WarmupProfiler()
    return _profiler


def reset_profiler():
    global _profiler
    _profiler = None


@contextmanager
def warmup_timer(label: str, category: str = "general", note: str = ""):
    """Context manager that times a warmup section."""
    p = get_warmup_profiler()
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        p.record(label, elapsed, category, note)


async def async_warmup_timer(label: str, category: str = "general", note: str = ""):
    """Async context manager that times a warmup section."""
    p = get_warmup_profiler()
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000
        p.record(label, elapsed, category, note)

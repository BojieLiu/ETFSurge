# -*- coding: utf-8 -*-
"""round34 R103+R108: IC 历史回填管道两处构造缺陷。

R103（§4.1）：`kline_depth = max(len(rws) ...)` 把场外联接基金净值序列（行无 date
键，如 019633 len=658）计入深度 → skip 阈值 `max(depth-30, 200)` 被顶高至 628，
DB 已有 502 恒 < 628 → **每次启动都重跑完整回填**（~56s CPU 白跑，违背 R102
「重填后应跳过」意图）。修复：深度只统计「K 线行」（首行含非空 date 键的序列）
——与回填日期轴消费语义一致（sina/baostock/netease 路径行统一规整为 date 键）。

R108（§4.6）：回填 kline 只装 {close, dates} 两键，缓存行内 open/high/low/volume
被丢弃 → truncated 展开恒空数组 → atr/vol_ratio/vwap/amount_stability/kdj×3
七个纯 K 线因子历史恒无法入算（IC 仅 n≈7-9，vwap 冻结 245）。修复：五列与 close
同条件收集（列长恒等）；truncated 展开（kd["open"] 条件式）自此自然生效零改动。

无网络：纯函数断言（模块级 helper，round28 _wait_for_kline_rows 提取先例）。
"""
import pytest

from app.main import _build_backfill_kline, _kline_depth_from_rows


def _kline_rows(n_days=500, start=1.0):
    """模拟 K 线标的行序列（sina 规整形态：date/open/close/high/low/volume）。"""
    return [
        {"date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}", "open": start + i * 0.01,
         "close": start + i * 0.01 + 0.005, "high": start + i * 0.01 + 0.01,
         "low": start + i * 0.01, "volume": 1e6 + i}
        for i in range(n_days)
    ]


def _nav_rows(n_points=658):
    """模拟场外联接基金净值序列（旧格式：day 键空串、无 date/open/volume）。"""
    return [{"day": "", "nav": 1.0 + i * 0.001} for i in range(n_points)]


class TestR103KlineDepthIgnoresNavRows:
    def test_kline_depth_ignores_nav_rows(self):
        """混入超深净值序列不得顶高 kline_depth（复刻 510300[500] + 019633[658]）。"""
        rows = {
            "510300": _kline_rows(500),
            "019633": _nav_rows(658),
        }
        assert _kline_depth_from_rows(rows) == 500, (
            "净值序列（无 date 键）必须被过滤，否则 skip 阈值被击穿每启重跑"
        )

    def test_all_nav_rows_falls_back_to_zero(self):
        """负向：全净值行 → depth==0 → max(0-30, 200)=200 兜底，不崩溃不误跳过
        （fresh 库仍会触发完整回填，行为与 R102 一致）。"""
        rows = {"019633": _nav_rows(658), "110011": _nav_rows(300)}
        assert _kline_depth_from_rows(rows) == 0

    def test_empty_or_malformed_entries_ignored(self):
        """边界：非 list / 空 list 行安全忽略。"""
        rows = {"A": None, "B": [], "C": _kline_rows(120), "D": "not-a-list"}
        assert _kline_depth_from_rows(rows) == 120

    def test_empty_rows_dict(self):
        assert _kline_depth_from_rows({}) == 0

    def test_skip_threshold_arithmetic_holds_after_filter(self):
        """验收口径：502 交易日 DB ≥ 过滤后深度-30 → 第二次启动走 skip 分支。"""
        rows = {"510300": _kline_rows(500), "159338": _kline_rows(498),
                "019633": _nav_rows(658)}
        depth = _kline_depth_from_rows(rows)
        existing = 502
        assert existing >= max(depth - 30, 200), "修复后应满足 skip 判据"


class TestR108BackfillKlineCarriesOhlcv:
    def test_five_columns_collected_with_close_condition(self):
        """回填 kline 必须带齐 OHLCV 五列，且各列长与 close 恒等（同条件收集）。"""
        rows = {"510300": _kline_rows(500), "159338": _kline_rows(480)}
        kline = _build_backfill_kline(rows, syms={"510300", "159338"})
        assert set(kline) == {"510300", "159338"}
        for sym, kd in kline.items():
            n = len(kd["close"])
            assert n >= 5
            for col in ("dates", "open", "high", "low", "volume"):
                assert col in kd and len(kd[col]) == n, (
                    f"{sym}.{col} 缺失或长度 != close（{len(kd.get(col, []))} vs {n}）"
                )
            # 值非空（sina 行五列齐全；truncated 展开的 kd.get("open") 条件自此生效）
            assert kd["high"][n - 1] is not None
            assert kd["volume"][n - 1] is not None

    def test_pool_excludes_symbols_not_in_syms(self):
        """池外 symbol 不进回填 kline（与原实现一致）。"""
        rows = {"510300": _kline_rows(100), "600000": _kline_rows(100)}
        kline = _build_backfill_kline(rows, syms=["510300"])
        assert set(kline) == {"510300"}

    def test_close_only_source_keeps_legacy_shape(self):
        """负向（防回归现状）：源行本身无 OHLCV 字段时，四列为空列表——
        即旧行为（此时 atr/kdj 无法计算属数据事实，非管道丢列）。"""
        rows = {"510300": [
            {"date": f"2026-08-{i + 1:02d}", "close": 1.0 + i} for i in range(30)
        ]}
        kline = _build_backfill_kline(rows, syms={"510300"})
        kd = kline["510300"]
        assert len(kd["close"]) == 30
        assert all(kd[c] == [] or all(v is None for v in kd[c])
                   for c in ("open", "high", "low", "volume"))

    def test_short_series_dropped(self):
        """closes <5 的短序列不进回填 kline（与原实现一致）。"""
        rows = {"510300": _kline_rows(3)}
        assert _build_backfill_kline(rows, syms={"510300"}) == {}

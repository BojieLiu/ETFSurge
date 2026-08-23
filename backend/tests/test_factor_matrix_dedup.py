# -*- coding: utf-8 -*-
"""round35 §12-P0-4 (docs/round35-architecture-review.md §12.3) —
get_factor_matrix 输入键去重：{code}_raw 孪生键不得进入因子矩阵。

根因：refresh_pool 把 aggregate_factor_scores 结果（顶层聚合键 + 原始点分键）
写入池内 factor_scores，且 compute() 为每个因子额外落 {code}_raw 保留键
（factor_registry.py:1546）。get_factor_matrix 此前按「数值即收」，导致同一信号
以三重表示进入矩阵（如 technical.macd.macd / *.macd_raw / 聚合键 technical），
任何全键迭代类消费（覆盖率统计、LLM 上下文转储）被系统性放大。

负向断言：矩阵行内出现任何 ``*_raw`` 键即 FAIL（防回归）。
兼容锚点：
- O4 raw 因子（rsi 等 standardization=raw 主键）保持真实值不受本改动影响；
- rationale 的 _raw 偏好读取有主键 fallback（rationale.py:200/:214），剥离
  矩阵层 _raw 不破坏措辞链路（rsi 主键经 O4 保真；macd 回退 z-score 主键）。
"""
import pytest

from app.services.market_data_hub import MarketDataHub


def _hub_with_pool(rows: dict[str, dict]) -> MarketDataHub:
    hub = MarketDataHub()
    hub._pool = {
        "core": [
            {"symbol": sym, "factor_scores": dict(fs)} for sym, fs in rows.items()
        ],
    }
    return hub


def test_matrix_strips_raw_twin_keys():
    """负向（对旧实现必红）：*_raw 孪生键不得出现在矩阵行中。"""
    hub = _hub_with_pool({
        "510300": {
            "technical.macd.macd": 0.5,
            "technical.macd.macd_raw": 123.4,   # 孪生保留键——旧实现会带进矩阵
            "etf.return_1m": 2.0,
            "etf.return_1m_raw": 2.0,           # 同上
            "momentum": 0.7,                    # 顶层聚合键（refresh_pool 并存写入）
        },
        "512890": {
            "technical.macd.macd": -0.3,
            "technical.macd.macd_raw": -45.6,
            "etf.return_1m": -1.0,
            "etf.return_1m_raw": -1.0,
            "momentum": -0.4,
        },
    })
    matrix = hub.get_factor_matrix()

    assert set(matrix) == {"510300", "512890"}
    for sym, row in matrix.items():
        raw_keys = [k for k in row if k.endswith("_raw")]
        assert not raw_keys, f"{sym} 矩阵行残留 _raw 孪生键: {raw_keys}"
    # 顶层聚合键与点分主键仍保留（决策与展示两条链路的输入不缺失）
    assert "momentum" in matrix["510300"]
    assert "technical.macd.macd" in matrix["510300"]
    assert "etf.return_1m" in matrix["510300"]


def test_matrix_keeps_o4_raw_standardization_main_key_real():
    """O4 兼容锚：standardization=raw 的主键（rsi_14，0-100 真实值）保持原值，
    仅剥离其 _raw 孪生——真实量纲展示与 rationale 措辞链路不受影响。"""
    hub = _hub_with_pool({
        "510300": {"technical.rsi.rsi_14": 72.5, "technical.rsi.rsi_14_raw": 72.5},
        "512890": {"technical.rsi.rsi_14": 31.0, "technical.rsi.rsi_14_raw": 31.0},
    })
    matrix = hub.get_factor_matrix()
    for sym, row in matrix.items():
        assert not [k for k in row if k.endswith("_raw")]
    # rsi_14 是 raw 标准化因子 → 跳过截面 z-score，真实值原样保留
    assert matrix["510300"]["technical.rsi.rsi_14"] == pytest.approx(72.5)
    assert matrix["512890"]["technical.rsi.rsi_14"] == pytest.approx(31.0)


def test_matrix_zscore_still_applied_to_non_raw_factors():
    """行为保持：非 raw 因子的截面 z-score 归一化照常生效（均值≈0、有区分度）。"""
    hub = _hub_with_pool({
        "510300": {"technical.macd.macd": 1.0, "technical.macd.macd_raw": 99.0},
        "512890": {"technical.macd.macd": -1.0, "technical.macd.macd_raw": -99.0},
        "518880": {"technical.macd.macd": 0.0, "technical.macd.macd_raw": 0.0},
    })
    matrix = hub.get_factor_matrix()
    vals = [matrix[s]["technical.macd.macd"] for s in ("510300", "512890", "518880")]
    assert abs(sum(vals) / len(vals)) < 1e-6          # 截面中心化
    assert max(vals) - min(vals) > 1.0                # 有区分度（未被拍平）

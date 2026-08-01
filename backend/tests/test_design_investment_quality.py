"""TDD: F1-8 / §9.7 R3+R5 — rationale 绑定标的属性 + 信号聚合「双弱不判多」。

R3（rationale）：
  1. rationale 无模板拼接缺陷（无截断、无「在方案中在方案中」重复）
  2. 科创类指数（589850/589980）不出现「压舱石/低波动」措辞
  3. 低波宽基（沪深300）保留「压舱石/低波动」池
R5（信号聚合）：
  4. 技术<0 且 估值<0（动量拉不平）→ 综合信号非 buy/偏多，至多 hold
  5. 单因子极端值（估值 +9）→ 聚合前截断至 ≤1.0
  6. 正常偏多场景仍输出 buy（不压幅度）
"""
import pytest

from app.engine.rationale import build_rationale, _style_probe
from app.analysis.signal import composite_signal


# ── R3: rationale 绑定标的属性 ─────────────────────────────────

def _build(code, name, layer="core", tracked_index="", strategy="balanced"):
    return build_rationale(
        code=code, layer=layer, strategy=strategy,
        meta={"name": name, "tracked_index": tracked_index},
        factor_scores={"technical": 0.3, "valuation": 0.2, "momentum": 0.1},
        regime="range_bound",
    )


def test_rationale_no_template_corruption():
    """无截断、无「在方案中在方案中」重复拼接。"""
    text = _build("562320", "沪深300价值ETF", "core", "沪深300")
    assert "在方案中在方案中" not in text, f"重复拼接: {text}"
    assert "在方案中" not in text, f"不应出现裸「在方案中」: {text}"
    # 不以「压」等半截词结尾
    assert not text.endswith("压") and not text.endswith("在方案中")


def test_kc_index_not_labeled_pillar():
    """科创类指数不出现「压舱石/低波动」措辞，且使用高波成长池措辞。"""
    for code, name in (("589850", "科创50ETF"), ("589980", "科创100ETF")):
        text = _build(code, name, "core", "科创50" if code == "589850" else "科创100")
        assert "压舱石" not in text, f"{code} 被冠压舱石: {text}"
        assert "低波动" not in text, f"{code} 被冠低波动: {text}"
        assert any(w in text for w in ("科创成长", "高弹性", "弹性充足", "高波动成长", "高 Beta", "进攻")), \
            f"{code} 应体现高波成长属性: {text}"


def test_wide_basis_keeps_pillar_pool():
    """低波宽基（沪深300）归入低波宽基池（可含压舱石/低波动/底仓/β 措辞）。"""
    text = _build("510300", "沪深300ETF", "core", "沪深300")
    assert _style_probe({"name": "沪深300ETF", "tracked_index": "沪深300"}) == "low_vol_wide"
    # 不被误判为高波成长
    assert not any(w in text for w in ("高弹性成长", "高 Beta", "弹性充足")), f"宽基被误标成长: {text}"


def test_style_probe_kc_forced_high_growth():
    """科创指数强制归入高波成长池。"""
    assert _style_probe({"name": "科创50ETF", "tracked_index": "科创50"}) == "high_growth"
    assert _style_probe({"name": "半导体ETF", "tracked_index": ""}) == "high_growth"
    assert _style_probe({"name": "黄金ETF", "tracked_index": "黄金"}) == "defensive"
    assert _style_probe({"name": "沪深300ETF", "tracked_index": "沪深300"}) == "low_vol_wide"


# ── R5: 信号聚合 ───────────────────────────────────────────────

def test_dual_weak_not_bullish():
    """技术<0 且 估值<0，动量不足以拉平 → 非 buy/偏多，至多 hold。"""
    # 589720 实测场景：技术 -0.408 / 估值 -0.462 / 动量 +1.047（极端封顶 1.0）
    result = composite_signal(technical=-0.408, valuation=-0.462, momentum=1.047)
    assert result["signal"] in ("hold", "sell"), f"双弱不应判多: {result}"
    assert result["score"] <= 0.0, f"双弱得分应 ≤0: {result}"


def test_valuation_extreme_capped():
    """单因子极端值（估值 +9）→ 聚合前截断至 ≤1.0。"""
    result = composite_signal(technical=0.2, valuation=9.0, momentum=0.5)
    assert result["components"]["valuation"] <= 1.0
    # 封顶后估值 1.0 → 综合分 = 0.4*0.2 + 0.4*1.0 + 0.2*0.5 = 0.58 → buy
    assert result["score"] <= 1.0


def test_strong_tech_val_bullish():
    """技术/估值双强 → buy（不压幅度）。"""
    result = composite_signal(technical=0.8, valuation=0.9, momentum=0.6)
    assert result["signal"] == "buy"
    assert result["score"] > 0.5


def test_all_neutral_hold():
    """全中性 → hold。"""
    result = composite_signal(technical=0.0, valuation=0.0, momentum=0.0)
    assert result["signal"] == "hold"

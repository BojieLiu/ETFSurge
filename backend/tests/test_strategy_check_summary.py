"""R6-F13 (round6 §十五 R6-15): 策略检查兜底 summary 文案区分限流/超时/快速失败。

背景：实际 500 快速失败（10s）时文案仍写"LLM 分析超时（60s 未返回）"——
模板文案未随 R5-1-6 更新。修复：按 get_last_llm_error 内容区分
「限流 / 响应超时 / 服务端错误」，与 LLM 层诊断一致。
"""
from app.services.portfolio_service import _build_llm_fail_summary


def test_fail_summary_rate_limit():
    """诊断含 429/限流 → "LLM 限流"。"""
    s = _build_llm_fail_summary(10.0, "HTTP 429 Rate limit exceeded")
    assert "LLM 限流" in s, s
    assert "429" in s
    assert "已用规则引擎兜底" in s


def test_fail_summary_timeout():
    """诊断含 timeout → "LLM 响应超时"。"""
    s = _build_llm_fail_summary(60.0, "HTTPSConnectionPool timed out")
    assert "LLM 响应超时" in s, s


def test_fail_summary_server_error():
    """5xx 快速失败（非超时非限流）→ "LLM 服务端错误"，旧"超时 60s"文案不出现。"""
    s = _build_llm_fail_summary(10.0, "Server error '500 Internal Server Error'")
    assert "LLM 服务端错误" in s, s
    assert "超时（60s" not in s  # 旧文案残留不得出现


def test_fail_summary_unknown_diag():
    """无诊断 → 归类服务端错误且含"未知"。"""
    s = _build_llm_fail_summary(30.0, "")
    assert "服务端错误" in s
    assert "未知" in s

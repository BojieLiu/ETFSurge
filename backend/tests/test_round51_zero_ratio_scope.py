"""round51 方案 E (R166): zero_ratio 口径隔离.

背景 (round51 §2.3): /factors/active 的 zero_ratio 挂在 ic_tracker._zero_ratio
（ic_tracker.py:242），语义 =「该因子参与 IC 计算批次里的非有意义值占比」
（样本仅覆盖 IC 窗口内交易日），不是「当前因子矩阵零值占比」。round39 诊断轮
把它当矩阵口径使用 → R146/R149 误判（news_heat 实际已生效却被判断链）。

修复（方案 E，文档 §4.2）:
- factors.py: /factors/active 响应附 zero_ratio_scope="ic_batch" 字段 +
  zero_ratio_note 防误读注释；
- data_health_check.py: critical 清单处补口径注释（两口径不可互替）。
"""
from __future__ import annotations

import pytest


class TestFactorsActiveScope:
    """/factors/active 响应必须显式声明 zero_ratio 口径。"""

    @pytest.mark.asyncio
    async def test_response_declares_ic_batch_scope(self, monkeypatch):
        """响应 body 含 zero_ratio_scope='ic_batch'（负向: 缺字段即误用温床）。"""
        from app.routers import factors as fr

        # 清掉 60s 响应缓存, 保证走到构造 body 的路径
        monkeypatch.setattr(fr, "_get_cached", lambda ck, ttl=60: None)

        captured: dict = {}

        class _FakeResp:
            def __init__(self, content, headers):
                self.content = content
                self.headers = headers

        def _fake_json_response(content, headers=None):
            captured["body"] = content
            return _FakeResp(content, headers or {})

        monkeypatch.setattr(fr, "JSONResponse", _fake_json_response)
        monkeypatch.setattr(fr, "_set_cache", lambda *a, **kw: None)

        class _FakeDB:
            async def execute(self, *a, **kw):
                class _R:
                    def scalars(self):
                        return self

                    def all(self):
                        return []

                return _R()

        await fr.get_active_factors(db=_FakeDB())

        body = captured.get("body") or {}
        assert body.get("zero_ratio_scope") == "ic_batch", \
            f"zero_ratio_scope 缺失或错误: {body.get('zero_ratio_scope')!r}"
        note = body.get("zero_ratio_note") or ""
        assert "ic" in note.lower() and "矩阵" in note, \
            f"zero_ratio_note 必须说明两种口径不可互替: {note!r}"

    def test_ic_tracker_zero_ratio_docstring_states_scope(self):
        """ic_tracker._zero_ratio 计算处 docstring/注释声明 IC 批次口径。"""
        import inspect

        from app.factors import ic_tracker as it

        src = inspect.getsource(it)
        # 计算点附近必须有口径声明（防后人再误读）
        assert "ic_batch" in src or "IC 批次" in src

"""round39-熔断三件套 (R143 改进): TTL 分级 / 去连坐 / 永久错误摘除。

设计为单测文件覆盖以下失败用例 (TDD 红灯):
- TTL 分级: 429 (quota) 30min vs 其它 (transient) 5min
- 去连坐: 单一 (provider,model) 429 不再触发 llm_quota_gate.mark_exhausted() 全局暂停
- 永久错误摘除: 400 "Model is unavailable" / 401 "not supported" / 403 "not available in your country"
  → mark_long_cooldown + model_catalog.mark_excluded

写时 mock 时间 (monotonic) 来精确控制 TTL 边界。
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.analysis import llm
from app.analysis.llm import gates
from app.analysis.llm import model_catalog as catalog_mod
from app.analysis.llm.gates import (
    _CIRCUIT_FAIL_THRESHOLD,
    _CIRCUIT_TTL,
    reset_circuit,
)


# ── 辅助 ─────────────────────────────────────────────────────────


def _make_429_exc():
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(429, request=req, headers={"Retry-After": "30"})
    return httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)


def _make_permanent_400_exc(msg: str = "Model is unavailable"):
    """永久性错误：400 + 特征文案（model not available / 永久失效）。"""
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    # opencode_zen / b.ai 真实特征文案
    body = (
        '{"error":{"type":"server_error","message":"Error from provider (Console): '
        f'Upstream request failed: {msg}"}}'
    ).encode()
    resp = httpx.Response(400, request=req, content=body)
    return httpx.HTTPStatusError("400 Bad Request", request=req, response=resp)


def _make_5xx_exc():
    req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
    resp = httpx.Response(500, request=req)
    return httpx.HTTPStatusError("500", request=req, response=resp)


@pytest.fixture(autouse=True)
def _reset():
    reset_circuit()
    catalog_mod.model_catalog._exclusions.clear()
    yield
    reset_circuit()
    catalog_mod.model_catalog._exclusions.clear()


# ── TTL 分级 ──────────────────────────────────────────────────────


class TestCircuitTtlByErrorType:
    """429 (quota) → 30min 冷却；5xx/timeout (transient) → 5min 冷却。
    解决锯齿复探：30min TTL 与免费模型配额窗口（小时级）对齐，避免 5min 复探反复撞 429。
    """

    def test_429_opens_circuit_with_30min_ttl(self):
        """429 触发 OPEN → opened_at 距 now < 30min 时仍 OPEN（_circuit_allow False）。"""
        fake = {"t": 1000.0}

        def fm():
            return fake["t"]

        with patch.object(gates.time, "monotonic", side_effect=fm):
            gates._circuit_record_failure("zen", is_quota_error=True, model="m1")
            # 立即查询：OPEN
            assert gates._circuit_state("zen", "m1") == "OPEN"
            # 28min 后续：仍 OPEN（TTL=30min 未到）
            fake["t"] = 1000.0 + 28 * 60
            assert gates._circuit_state("zen", "m1") == "OPEN"
            # 31min 后续：HALF_OPEN（可复探）
            fake["t"] = 1000.0 + 31 * 60
            assert gates._circuit_allow("zen", "m1") is True
            assert gates._circuit_state("zen", "m1") == "HALF_OPEN"

    def test_5xx_keeps_5min_ttl(self):
        """5xx 触发瞬态 OPEN → 4min 后续仍 OPEN；6min 后续可复探（保持旧 5min TTL）。"""
        fake = {"t": 1000.0}

        def fm():
            return fake["t"]

        with patch.object(gates.time, "monotonic", side_effect=fm):
            # 累计阈值 2 次失败（5xx 走累计分支）
            for _ in range(_CIRCUIT_FAIL_THRESHOLD):
                gates._circuit_record_failure("zen", is_quota_error=False, model="m1")
            assert gates._circuit_state("zen", "m1") == "OPEN"
            # 4min 后续：仍 OPEN
            fake["t"] = 1000.0 + 4 * 60
            assert gates._circuit_state("zen", "m1") == "OPEN"
            # 6min 后续：HALF_OPEN（5min TTL 已过）
            fake["t"] = 1000.0 + 6 * 60
            assert gates._circuit_allow("zen", "m1") is True

    def test_429_ttl_constant_exported(self):
        """_CIRCUIT_TTL_QUOTA 常量应被定义且为 1800s（30min）。"""
        from app.analysis.llm import gates as g2
        # 期望新增常量 _CIRCUIT_TTL_QUOTA = 1800.0
        assert hasattr(g2, "_CIRCUIT_TTL_QUOTA"), "需定义 _CIRCUIT_TTL_QUOTA"
        assert g2._CIRCUIT_TTL_QUOTA == 1800.0


# ── 去连坐 ────────────────────────────────────────────────────────


class TestNoGlobalLockoutOnSingleModel429:
    """单 (provider, model) 429 不再触发 llm_quota_gate.mark_exhausted() 全局暂停。

    原行为：gates._circuit_record_failure(is_quota_error=True) 调
    llm_quota_gate.mark_exhausted() → 全局 60s 暂停，连带其他 provider 一并卡住。
    新行为：仅 (provider, model) 熔断；全局门禁只在「整 provider 全 OPEN」时触发。
    """

    def test_single_429_does_not_mark_exhausted(self):
        from app.analysis import llm as llm_mod

        fake = {"t": 1000.0}
        with patch.object(gates.time, "monotonic", side_effect=lambda: fake["t"]):
            # 重置全局门禁
            llm_mod.llm_quota_gate._exhausted_until = 0.0
            gates._circuit_record_failure("zen", is_quota_error=True, model="deepseek-v4-flash-free")
            # 期望：exhausted_until 仍为 0（未触发全局暂停）
            assert llm_mod.llm_quota_gate._exhausted_until == 0.0, (
                f"单模型 429 不应触发全局暂停，实际 exhausted_until="
                f"{llm_mod.llm_quota_gate._exhausted_until}"
            )

    def test_all_models_429_triggers_global_lockout(self):
        """整 provider 下所有 model 都 429 → 触发全局暂停（兜底）。"""
        from app.analysis import llm as llm_mod

        fake = {"t": 1000.0}
        with patch.object(gates.time, "monotonic", side_effect=lambda: fake["t"]):
            llm_mod.llm_quota_gate._exhausted_until = 0.0
            # 准备：先让 m1/m2 都 429 OPEN（这是 _circuit_record_failure_all_models_quota
            # 的前提——必须全 OPEN 才触发全局暂停）
            gates._circuit_record_failure("zen", is_quota_error=True, model="m1")
            gates._circuit_record_failure("zen", is_quota_error=True, model="m2")
            assert gates._circuit_state("zen", "m1") == "OPEN"
            assert gates._circuit_state("zen", "m2") == "OPEN"
            llm_mod.llm_quota_gate._exhausted_until = 0.0  # 清掉 _circuit_record_failure 单模型 429 残留
            # 调用兜底入口
            gates._circuit_record_failure_all_models_quota("zen", models=["m1", "m2"])
            # 期望：exhausted_until > 0
            assert llm_mod.llm_quota_gate._exhausted_until > 0.0


# ── 永久错误摘除 ─────────────────────────────────────────────────


class TestPermanentErrorAutoExclude:
    """永久性错误（400/401/403 + 特征文案）→ mark_long_cooldown + model_catalog.mark_excluded。

    适用：
    - 400 "Model is unavailable" / "Upstream request failed: ..."
    - 401 "is not supported" / "Authorization" 失败
    - 403 "not available in your country" / "Access restricted"
    """

    def test_400_model_unavailable_marks_long_cooldown_and_excluded(self):
        """400 'Model is unavailable' → 永久摘除：mark_long_cooldown + mark_excluded。"""
        from app.analysis import llm as llm_mod

        exc = _make_permanent_400_exc("Model is unavailable")
        llm_mod._circuit_record_failure(
            "opencode_zen", is_quota_error=False, model="deepseek-v4-flash-free", exc=exc
        )
        # 长冷却已打
        assert gates.is_long_cooldown("opencode_zen", "deepseek-v4-flash-free") is True
        # catalog 排除表已加
        assert catalog_mod.model_catalog.is_excluded("opencode_zen", "deepseek-v4-flash-free") is True
        # 普通熔断也 OPEN（防止 TTL 后复探）
        assert gates._circuit_state("opencode_zen", "deepseek-v4-flash-free") == "OPEN"

    def test_401_not_supported_marks_excluded(self):
        """401 'Model X is not supported' → 永久摘除。"""
        from app.analysis import llm as llm_mod

        body = b'{"error":{"message":"Model x-preview-f-free is not supported"}}'
        req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
        resp = httpx.Response(401, request=req, content=body)
        exc = httpx.HTTPStatusError("401", request=req, response=resp)

        llm_mod._circuit_record_failure("b_ai", is_quota_error=False, model="gpt-5-pro", exc=exc)
        assert catalog_mod.model_catalog.is_excluded("b_ai", "gpt-5-pro") is True
        assert gates.is_long_cooldown("b_ai", "gpt-5-pro") is True

    def test_403_country_blocked_marks_excluded(self):
        """403 'not available in your country' → 永久摘除。"""
        from app.analysis import llm as llm_mod

        body = b'{"error":{"message":"This model is not available in your country."}}'
        req = httpx.Request("POST", "http://llm.test/v1/chat/completions")
        resp = httpx.Response(403, request=req, content=body)
        exc = httpx.HTTPStatusError("403", request=req, response=resp)

        llm_mod._circuit_record_failure("opencode_zen", is_quota_error=False, model="muse-x", exc=exc)
        assert catalog_mod.model_catalog.is_excluded("opencode_zen", "muse-x") is True

    def test_transient_5xx_does_not_mark_excluded(self):
        """5xx/timeout → 不应摘除（瞬态错误可能自愈）。"""
        from app.analysis import llm as llm_mod

        exc = _make_5xx_exc()
        llm_mod._circuit_record_failure("zen", is_quota_error=False, model="m1", exc=exc)
        # 排除表不应有 m1
        assert not catalog_mod.model_catalog.is_excluded("zen", "m1")
        # 长冷却也不应有
        assert not gates.is_long_cooldown("zen", "m1")

    def test_timeout_does_not_mark_excluded(self):
        """timeout → 不应摘除。"""
        from app.analysis import llm as llm_mod

        exc = httpx.ReadTimeout("timeout")
        llm_mod._circuit_record_failure("zen", is_quota_error=False, model="m2", exc=exc)
        assert not catalog_mod.model_catalog.is_excluded("zen", "m2")
        assert not gates.is_long_cooldown("zen", "m2")

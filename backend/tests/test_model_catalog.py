"""§19 切片 1：免费模型目录 + 熔断 model 级粒度单测。

覆盖：
- Zen 过滤（-free 后缀 / Responses-API 家族排除 / 黑名单）；
- OpenRouter pricing 双零过滤 + 参数启发式降序 + 未知档排尾；
- zen_attempt_sequence 四护栏性质（无放回、跳过被阻、子集收缩）——固定种子
  属性断言（§19.9 验收 8 的切片部分）；
- gates model 级键（provider:model 与裸 provider 键互不串扰）+ 403 长冷却
  （不计普通熔断阈值，reset 清空）。

验证窗口纪律：全部夹具为合成清单——不得硬编码当日真实列表内容。
"""

import random

from app.analysis.llm import gates
from app.analysis.llm.model_catalog import (
    CatalogEntry,
    ModelCatalog,
    estimate_params_b,
    zen_attempt_sequence,
)


# ── 启发式 ────────────────────────────────────────────────────────

def test_estimate_params_b_takes_max_across_fields():
    assert estimate_params_b(
        "dots-studio/dots-3-note-preview:free",
        "Dots 3 Note (280B)",
        "A 975B-parameter MoE… actually mentions 120B too",
    ) == 975.0
    assert estimate_params_b("no numbers here") is None
    assert estimate_params_b(None, "") is None


# ── Zen 过滤 ──────────────────────────────────────────────────────

def _catalog_with_zen(ids: list[str], excluded: set[str] | None = None) -> ModelCatalog:
    c = ModelCatalog(ttl_seconds=9999)
    for m in excluded or ():
        c.mark_excluded("opencode_zen", m)
    c._zen = c._filter_zen({"data": [{"id": i} for i in ids]})
    c._ts = 1.0
    return c


def test_zen_filter_free_suffix_and_responses_family():
    c = _catalog_with_zen([
        "deepseek-v4-flash-free", "hy3-free", "x-preview-f-free",
        "muse-spark-1.2-contributor-free",   # Responses 家族 → 排除
        "deepseek-v4-flash",                  # 非 -free → 排除
        "gpt-plus",                           # 非 -free → 排除
    ])
    assert c.zen_pool() == ["deepseek-v4-flash-free", "hy3-free", "x-preview-f-free"]


def test_zen_blacklist_excluded():
    c = _catalog_with_zen(["a-free", "b-free"], excluded={"a-free"})
    assert c.zen_pool() == ["b-free"]


def test_stale_semantics():
    import time as _t
    c = ModelCatalog(ttl_seconds=50)
    assert c.stale is True          # 从未刷新
    c._ts = _t.monotonic()
    assert c.stale is False


# ── OpenRouter 过滤与排序 ─────────────────────────────────────────

def _or_body():
    return {"data": [
        {"id": "z/small:free", "name": "Small", "description": "",
         "context_length": 8000,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "a/huge:free", "name": "Huge 550B", "description": "",
         "context_length": 40000,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "m/mid:free", "name": "Mid 120B params", "description": "280B total",
         "context_length": 32000,
         "pricing": {"prompt": "0.000001", "completion": "0"}},   # 非双零 → 排除
        {"id": "u/unknown:free", "name": "Mystery", "description": "no size info",
         "pricing": {"prompt": "0", "completion": "0"}},
    ]}


def test_openrouter_filter_and_param_desc_order():
    c = ModelCatalog(ttl_seconds=9999)
    pool = c._filter_openrouter(_or_body())
    models = [e.model for e in pool]
    assert models == ["a/huge:free", "z/small:free", "u/unknown:free"], (
        "按参数量降序；未知档排尾且同档按 context 降序；付费档剔除"
    )
    huge = pool[0]
    assert huge.param_estimate_b == 550.0 and huge.context_length == 40000


def test_openrouter_tie_break_by_context_then_id():
    body = {"data": [
        {"id": "b/x:free", "name": "X 100B", "context_length": 8192,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "a/y:free", "name": "Y 100B", "context_length": 32768,
         "pricing": {"prompt": "0", "completion": "0"}},
    ]}
    pool = ModelCatalog()._filter_openrouter(body)
    assert [e.model for e in pool] == ["a/y:free", "b/x:free"]


# ── Zen 选择序列护栏 ──────────────────────────────────────────────

def test_sequence_no_replacement_and_skips_blocked():
    rng = random.Random(42)
    seq = zen_attempt_sequence(
        ["m1-free", "m2-free", "m3-free"],
        is_blocked=lambda m: m == "m2-free",
        rng=rng,
    )
    assert seq == ["m1-free", "m3-free"] or seq == ["m3-free", "m1-free"]
    assert len(seq) == len(set(seq))            # 无放回
    assert "m2-free" not in seq                 # 被阻成员不进序列


def test_sequence_allowed_subset_shrinks_domain():
    rng = random.Random(7)
    seq = zen_attempt_sequence(
        ["a-free", "b-free", "c-free"],
        is_blocked=lambda _: False,
        allowed_subset=["a-free", "c-free"],
        rng=rng,
    )
    assert set(seq) == {"a-free", "c-free"}, "JSON 路径限定子集生效（护栏 4）"


# ── gates：model 级键 + 长冷却 ────────────────────────────────────

def setup_function() -> None:
    gates.reset_circuit()


def test_model_level_key_isolated_from_provider_key():
    """provider:model 熔断不影响同 provider 其它模型的尝试路径。

    注：裸键 ``_circuit_state(provider)`` 是聚合视图（任一分支 OPEN 即 OPEN，
    行为锚语义）；隔离契约体现在 **allow 尝试路径**——死模型被拒、活模型放行。
    """
    gates._circuit_record_failure("opencode_zen", False, model="dead-free")
    gates._circuit_record_failure("opencode_zen", False, model="dead-free")
    assert gates._circuit_state("opencode_zen", "dead-free") == "OPEN"
    assert gates._circuit_state("opencode_zen", "alive-free") == "CLOSED"
    # 聚合视图：存在 OPEN 分支 → provider 级查询报 OPEN
    assert gates._circuit_state("opencode_zen") == "OPEN"
    # 隔离的关键在尝试路径：死分支拒绝、活分支与裸键旧用法不受牵连
    assert gates._circuit_allow("opencode_zen", "dead-free") is False
    assert gates._circuit_allow("opencode_zen", "alive-free") is True
    gates._circuit_record_failure("deepseek", True)   # 裸键旧用法（行为锚形态）
    assert gates._circuit_state("deepseek") == "OPEN"
    assert gates._circuit_allow("deepseek") is False


def test_long_cooldown_blocks_but_not_via_fail_threshold():
    """403 门禁长冷却直接拒绝尝试，且不需要两次失败才 OPEN。"""
    assert gates._circuit_allow("openrouter", "gated:free") is True
    gates.mark_long_cooldown("openrouter", "gated:free")
    assert gates.is_long_cooldown("openrouter", "gated:free")
    assert gates._circuit_allow("openrouter", "gated:free") is False
    # 其它模型不受牵连；裸 provider 查询也不受 model 级长冷却影响
    assert gates._circuit_allow("openrouter", "other:free") is True
    assert gates._circuit_allow("openrouter") is True


def test_reset_clears_long_cooldown():
    gates.mark_long_cooldown("openrouter", "gated:free")
    gates.reset_circuit()
    assert gates.is_long_cooldown("openrouter", "gated:free") is False


# ── §19 切片 2: get_configured_providers 目录扩展 ────────────────

def _patch_settings(monkeypatch, **overrides):
    from app.analysis import provider as prov
    defaults = {
        "llm_primary_provider": "opencode_zen",
        "opencode_zen_api_key": "kz",
        "opencode_zen_model": "deepseek-v4-flash-free",
        "openrouter_api_key": "",
        "deepseek_api_key": "",
        "llm_zen_allowed_models": "",
        # b.ai 默认空 (R40 + R45 测试隔离: 不让 .env 配 key 漏到 model_catalog 测试)
        "b_ai_api_key": "",
        "b_ai_allowed_models": "",
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setattr(prov.settings, k, v)
    return prov


def test_providers_expand_with_catalog(monkeypatch):
    """目录池可用：Zen 随机序列在前、OpenRouter 中间层、DeepSeek 付费殿后。"""
    from app.analysis import provider as prov
    c = ModelCatalog(ttl_seconds=9999)
    c._zen = ["b-free", "a-free"]
    c._openrouter = [CatalogEntry(model="or/big:free", provider="openrouter",
                                   param_estimate_b=550.0)]
    monkeypatch.setattr("app.analysis.llm.model_catalog.model_catalog", c)
    prov = _patch_settings(monkeypatch,
                           openrouter_api_key="kor",
                           deepseek_api_key="kd")
    random.seed(1234)
    ps = prov.get_configured_providers()
    ids = [p.id for p in ps]
    assert ids[0] == "opencode_zen" and ids[-1] == "deepseek"
    assert ids.index("openrouter") < ids.index("deepseek"), "中间层在付费层之前"
    zen_models = [p.model for p in ps if p.id == "opencode_zen"]
    assert set(zen_models) == {"a-free", "b-free"}   # 池内无放回全试
    assert len(zen_models) == len(set(zen_models))
    or_p = next(p for p in ps if p.id == "openrouter")
    assert or_p.model == "or/big:free" and or_p.reasoning_effort is None


def test_providers_fallback_static_when_catalog_empty(monkeypatch):
    """目录空（未刷新）→ 现状静态单候选，诚实降级到旧行为。"""
    from app.analysis import provider as prov
    monkeypatch.setattr("app.analysis.llm.model_catalog.model_catalog",
                        ModelCatalog(ttl_seconds=9999))
    prov = _patch_settings(monkeypatch)
    ps = prov.get_configured_providers()
    assert [p.id for p in ps] == ["opencode_zen"]
    assert ps[0].model == prov.settings.opencode_zen_model


def test_zen_allowed_subset_shrinks_candidates(monkeypatch):
    """护栏 4：JSON 路径限定子集收缩随机域。"""
    from app.analysis import provider as prov
    c = ModelCatalog(ttl_seconds=9999)
    c._zen = ["a-free", "b-free", "c-free"]
    monkeypatch.setattr("app.analysis.llm.model_catalog.model_catalog", c)
    prov = _patch_settings(monkeypatch, llm_zen_allowed_models="a-free")
    ps = prov.get_configured_providers()
    assert {p.model for p in ps} == {"a-free"}


def test_zen_sequence_skips_open_circuit_models(monkeypatch):
    """§19.9-8：真实 gates 联动——复合键已 OPEN 的 model 分支不进尝试序列。"""
    from app.analysis import provider as prov
    c = ModelCatalog(ttl_seconds=9999)
    c._zen = ["x-free", "y-free"]
    monkeypatch.setattr("app.analysis.llm.model_catalog.model_catalog", c)
    prov = _patch_settings(monkeypatch)
    gates.reset_circuit()
    # x-free 连续两次失败 → 复合键 opencode_zen:x-free 达阈值 OPEN
    gates._circuit_record_failure("opencode_zen", False, model="x-free")
    gates._circuit_record_failure("opencode_zen", False, model="x-free")
    ps = prov.get_configured_providers()
    assert [p.model for p in ps] == ["y-free"], "OPEN 分支不得进入尝试序列"

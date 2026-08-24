"""三层 LLM 免费模型动态目录（round35 §19 / §19.9，探针双 GO）。

层链：Zen 免费池（层内**随机**）→ OpenRouter 免费池（层内**按参数量降序**）
→ DeepSeek 付费兜底（现状链不动）。本模块只负责「目录」：
- 拉取 + 过滤 + TTL 缓存 + last-known-good 降级（刷新失败不静默、不造假）；
- OpenRouter 参数量启发式（`数字+B` 正则扫 id/name/description 取最大值）；
- Zen 排除表（Responses-API 家族 / 实测不可用黑名单）。

选择序列生成也在此（纯函数、可种子化测试）：
- zen_attempt_sequence：护栏 1——无放回随机、跳过熔断中与排除表成员；
- JSON 路径「限定子集」（护栏 4）：allowed_models 非空时随机域收缩为子集。

不做（§19.6）：多账号池 / Responses 格式适配 / 质量评分择优。
验证窗口：列表内容随时漂移，测试只断言结构合法与过滤逻辑，不得硬编码当日清单。
"""

from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

CATALOG_TIMEOUT_S = 15.0

# Responses-API 家族排除（§19.4 脚注）：以 id 前缀维护，出现新格式家族在此扩表
_RESPONSES_API_PREFIXES = ("muse-spark",)

# OpenRouter 参数量启发式：id/name/description 中最大的「数字+B」
_PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[bB]\b")


@dataclass
class CatalogEntry:
    """单个免费候选模型。"""

    model: str
    provider: str                    # "opencode_zen" | "openrouter"
    param_estimate_b: float | None = None
    context_length: int | None = None


def estimate_params_b(*texts: str | None) -> float | None:
    """从若干文本片段提取最大参数量估计（单位 B）；无命中返回 None。"""
    best: float | None = None
    for t in texts:
        if not t:
            continue
        for m in _PARAM_RE.finditer(t):
            v = float(m.group(1))
            if best is None or v > best:
                best = v
    return best


def _is_responses_api_family(model_id: str) -> bool:
    return any(model_id.startswith(p) for p in _RESPONSES_API_PREFIXES)


class ModelCatalog:
    """双免费池目录：TTL 缓存 + last-known-good；刷新失败用旧池并 WARN。"""

    def __init__(self, ttl_seconds: float = 600.0) -> None:
        self.ttl = ttl_seconds
        self._zen: list[str] = []
        self._openrouter: list[CatalogEntry] = []
        self._ts: float = 0.0
        self._exclusions: set[str] = set()   # 实测不可用/质量差黑名单（护栏 3）

    # ── 拉取与过滤 ────────────────────────────────────────────

    async def refresh(
        self,
        zen_base_url: str,
        zen_api_key: str,
        openrouter_base_url: str,
        openrouter_api_key: str,
    ) -> None:
        """并发刷新两池；单池失败保留该池 last-known-good（WARN 不造假）。"""
        import httpx

        headers_zen = {"Authorization": f"Bearer {zen_api_key}"} if zen_api_key else {}
        headers_or = {"Authorization": f"Bearer {openrouter_api_key}"} if openrouter_api_key else {}
        zen_pool: list[str] | None = None
        or_pool: list[CatalogEntry] | None = None

        async with httpx.AsyncClient(trust_env=False, timeout=CATALOG_TIMEOUT_S) as client:
            if zen_base_url:
                try:
                    r = await client.get(f"{zen_base_url}/models", headers=headers_zen)
                    r.raise_for_status()
                    zen_pool = self._filter_zen(r.json())
                except Exception as e:
                    logger.warning("[model_catalog] zen pool refresh failed (keep last-known-good): %s", e)
            if openrouter_base_url and openrouter_api_key:
                try:
                    r = await client.get(f"{openrouter_base_url}/models", headers=headers_or)
                    r.raise_for_status()
                    or_pool = self._filter_openrouter(r.json())
                except Exception as e:
                    logger.warning("[model_catalog] openrouter pool refresh failed (keep last-known-good): %s", e)

        if zen_pool is not None:
            self._zen = zen_pool
        if or_pool is not None:
            self._openrouter = or_pool
        self._ts = time.monotonic()

    def _filter_zen(self, body: dict) -> list[str]:
        """-free 后缀 ∧ 非 Responses-API 家族 ∧ 不在排除表；确定性排序。"""
        ids = [str(d.get("id") or "") for d in (body.get("data") or [])]
        return sorted(
            i for i in ids
            if i.endswith("-free")
            and not _is_responses_api_family(i)
            and not self.is_excluded("opencode_zen", i)
        )

    def _filter_openrouter(self, body: dict) -> list[CatalogEntry]:
        """pricing 双零 → 免费；参数启发式降序、未知档排尾、同值 context 降序。"""
        entries: list[CatalogEntry] = []
        for d in (body.get("data") or []):
            mid = str(d.get("id") or "")
            pricing = d.get("pricing") or {}

            def _zero(v) -> bool:
                try:
                    return float(v) == 0.0
                except (TypeError, ValueError):
                    return False

            if not mid or not (_zero(pricing.get("prompt")) and _zero(pricing.get("completion"))):
                continue
            if self.is_excluded("openrouter", mid):
                continue
            name = str((d.get("name") or ""))
            desc = str((d.get("description") or ""))[:400]
            ctx = d.get("context_length")
            entries.append(CatalogEntry(
                model=mid,
                provider="openrouter",
                param_estimate_b=estimate_params_b(mid, name, desc),
                context_length=int(ctx) if isinstance(ctx, (int, float)) else None,
            ))
        entries.sort(key=self._or_sort_key)
        return entries

    @staticmethod
    def _or_sort_key(e: CatalogEntry):
        # param desc；未知(None)排尾；同值按 context desc 再按 id 稳定
        known = e.param_estimate_b is not None
        return (
            0 if known else 1,
            -(e.param_estimate_b or 0.0),
            -(e.context_length or 0),
            e.model,
        )

    # ── 只读视图 ──────────────────────────────────────────────

    @property
    def stale(self) -> bool:
        return (time.monotonic() - self._ts) > self.ttl

    def zen_pool(self) -> list[str]:
        return list(self._zen)

    def openrouter_pool(self) -> list[CatalogEntry]:
        return list(self._openrouter)

    def mark_excluded(self, provider: str, model: str) -> None:
        """实测不可用/质量差黑名单（护栏 3：排除表替代排序表）。"""
        self._exclusions.add(f"{provider}:{model}")

    def is_excluded(self, provider: str, model: str) -> bool:
        return f"{provider}:{model}" in self._exclusions


# ── 选择序列（纯函数，可种子化） ──────────────────────────────────


def zen_attempt_sequence(
    pool: list[str],
    is_blocked,
    allowed_subset: list[str] | None = None,
    rng: random.Random | None = None,
) -> list[str]:
    """Zen 层内随机尝试序列（§19.9 护栏 1/4）。

    - 无放回 random.sample（每模型至多试一次）；
    - is_blocked(model) 为 True 的成员不进序列（熔断 OPEN / 长冷却 / 黑名单）；
    - allowed_subset 非空时随机域收缩为「池 ∩ 子集」（JSON 路径收紧）。
    """
    rng = rng or random.Random()
    domain = [m for m in pool if m in set(allowed_subset)] if allowed_subset else list(pool)
    candidates = [m for m in domain if not is_blocked(m)]
    return rng.sample(candidates, k=len(candidates))


model_catalog = ModelCatalog()

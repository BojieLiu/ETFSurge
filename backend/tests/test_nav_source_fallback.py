"""
O18 (docs/archived/round7-rediagnosis.md §7 P20-①): premium_discount nav 源加固。

P20-①: 现有三级 nav 源（Sina http → QQ http → TTJ 日净值）在用户环境全失败
（http 明文被禁/被墙）→ premium_discount 因子 no_data。方向修正：先诊断再补源——
新增东财 push2 **https** 行情 f236（IOPV）源作为第三顺位（Sina/QQ 之后、TTJ 之前）。

覆盖:
① mock Sina 失败 → QQ 兜底；
② Sina+QQ 失败 → 东财 https 兜底；
③ 三级全失败 → 空（调用方走 TTJ 兜底 / gap 记录「缺 nav」）。
"""

import json

import pytest

from app.factors import factor_registry as fr


def _sina_list(symbols):
    prefixes = {"5": "sh", "6": "sh", "0": "sz", "1": "sz", "3": "sz"}
    return [f"{prefixes.get(s[0], 'sh')}{s}" for s in symbols]


def _qq_payload(symbols, navs):
    """构造 QQ 行情响应（~分隔，pos 31 = IOPV）。"""
    lines = []
    for sym, nav in zip(symbols, navs):
        parts = [""] * 33
        parts[2] = sym
        parts[3] = "1.0"
        parts[31] = str(nav)
        lines.append(f'v_{sym}="{"~".join(parts)}"')
    return "\n".join(lines)


class TestIopvFallbackChain:
    @pytest.mark.asyncio
    async def test_sina_failure_qq_fallback(self, monkeypatch):
        """① Sina 抛异常 → QQ 兜底（命中足够样本返回 QQ）。"""
        async def _sina_broken(s_list):
            raise RuntimeError("sina down")

        async def _qq_ok(s_list):
            return {"510300": {"price": 4.0, "nav": 4.01}, "560600": {"price": 1.0, "nav": 1.0}}

        monkeypatch.setattr(fr, "_fetch_iopv_from_sina", _sina_broken)
        monkeypatch.setattr(fr, "_fetch_iopv_from_qq", _qq_ok)

        data, source = await fr._fetch_iopv_chain(_sina_list(["510300", "560600"]), ["510300", "560600"])
        assert source == "qq"
        assert data["510300"]["nav"] == 4.01

    @pytest.mark.asyncio
    async def test_sina_qq_failure_em_fallback(self, monkeypatch):
        """② Sina+QQ 全失败 → 东财 https 兜底。"""
        async def _sina_broken(s_list):
            raise RuntimeError("sina down")

        async def _qq_broken(s_list):
            raise RuntimeError("qq down")

        async def _em_ok(s_list):
            return {"510300": {"price": 4.0, "nav": 4.01}}

        monkeypatch.setattr(fr, "_fetch_iopv_from_sina", _sina_broken)
        monkeypatch.setattr(fr, "_fetch_iopv_from_qq", _qq_broken)
        monkeypatch.setattr(fr, "_fetch_iopv_from_em", _em_ok)

        data, source = await fr._fetch_iopv_chain(_sina_list(["510300"]), ["510300"])
        assert source == "em"
        assert data["510300"]["nav"] == 4.01

    @pytest.mark.asyncio
    async def test_all_fail_returns_empty(self, monkeypatch):
        """③ 三级全失败 → 空（调用方走 TTJ 兜底 / gap 记录「缺 nav」）。"""
        async def _sina_broken(s_list):
            raise RuntimeError("sina down")

        async def _qq_broken(s_list):
            raise RuntimeError("qq down")

        async def _em_broken(s_list):
            raise RuntimeError("em down")

        monkeypatch.setattr(fr, "_fetch_iopv_from_sina", _sina_broken)
        monkeypatch.setattr(fr, "_fetch_iopv_from_qq", _qq_broken)
        monkeypatch.setattr(fr, "_fetch_iopv_from_em", _em_broken)

        data, source = await fr._fetch_iopv_chain(_sina_list(["510300"]), ["510300"])
        assert data == {}
        assert source == ""


class TestEmIopvParser:
    @pytest.mark.asyncio
    async def test_em_payload_parsed(self, monkeypatch):
        """东财 ulist JSON 解析：f12=code / f2=price / f236=iopv。"""
        payload = {
            "data": {
                "diff": [
                    {"f12": "510300", "f13": "1", "f2": 4.02, "f236": 4.01},
                    {"f12": "560600", "f13": "1", "f2": 1.05, "f236": "-"},
                    {"f12": "000001", "f13": "0", "f2": 11.0, "f236": None},
                ]
            }
        }

        async def _fake_run_sync(call, *args, timeout=8):
            return json.dumps(payload)

        monkeypatch.setattr("app.core.async_utils.run_sync", _fake_run_sync)
        result = await fr._fetch_iopv_from_em(_sina_list(["510300", "560600", "000001"]))
        assert result["510300"]["nav"] == 4.01
        assert result["510300"]["price"] == 4.02
        # 无效/缺失 IOPV 不计入
        assert "560600" not in result
        assert "000001" not in result

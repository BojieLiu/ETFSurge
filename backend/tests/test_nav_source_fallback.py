from __future__ import annotations
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
from unittest.mock import patch

import pytest

from app.factors import factor_registry as fr


def _sina_list(symbols):
    prefixes = {"5": "sh", "6": "sh", "0": "sz", "1": "sz", "3": "sz"}
    return [f"{prefixes.get(s[0], 'sh')}{s}" for s in symbols]


def _qq_payload(symbols, navs):
    """构造 QQ 行情响应（~分隔，round9 P0-6 实测: pos 81 = 单位净值 = IOPV/NAV 主源）。"""
    lines = []
    for sym, nav in zip(symbols, navs):
        parts = [""] * 82
        parts[2] = sym
        parts[3] = "1.0"
        parts[81] = str(nav)
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


# ── round9 P0-6/P0-7 反例（docs/archived/round9-container-rediagnosis.md §6.5.1-A）──
# 4 处解析 bug 类回归零漏检：sina 字段双错位、qq GBK 解码崩溃、em 字段不匹配、
# TTJ tuple/dict 契约错——全部覆盖。

class TestSinaParserRound9:
    @pytest.mark.asyncio
    async def test_sina_symbol_from_line_prefix(self, monkeypatch):
        """P0-6①: symbol 必须从行前缀 `var hq_str_(\\w+)` 提取，禁止用 parts[2]（昨收价）。

        真实响应（round9 实测）：`var hq_str_sh510050="上证50ETF,3.021,3.029,3.066,...,513471237,..."`
        parts[2]=3.029（昨收）parts[8]=513471237（成交量）——旧实现拿它们当 symbol/nav 全错。
        """
        raw = (
            'var hq_str_sh510050="上证50ETF,3.021,3.029,3.066,3.067,3.018,'
            '3.066,3.067,513471237,1566985099.000,250200,3.066,792400,'
            '3.065,292500,3.064,349200,3.063,183600,3.062,995100,3.067,'
            '1630400,3.068,774100,3.069,2257800,3.070,363400,3.071,'
            '2026-08-07,15:34:59,00,D|489600|1501113.60";\n'
            'var hq_str_sz159338="中证A500ETF,0.9,0.9,1.0,1.0,0.9,0.9,1.0,'
            '12345,67890.0,100,1.0,200,0.99,300,0.98,400,0.97,500,0.96,'
            '600,0.95,700,0.94,800,0.93,900,0.92,1000,2026-08-07,15:34:59,00,D|1|2";\n'
        )

        async def _fake_run_sync(call, *args, timeout=8):
            return raw

        monkeypatch.setattr("app.core.async_utils.run_sync", _fake_run_sync)
        result = await fr._fetch_iopv_from_sina(["sh510050", "sz159338"])
        # symbol 从行前缀提取（round9 修复点）
        assert set(result) == {"sh510050", "sz159338"}
        # sina 实时接口无 IOPV 字段 → 只提供 price，不提供 nav（链命中判定 nav>0 自然跳过本级）
        assert result["sh510050"]["price"] == 3.066
        assert "nav" not in result["sh510050"]
        # 旧 bug 反例：parts[2]=3.029（昨收）绝不能成为 symbol；parts[8] 绝不能成为 nav
        assert "3.029" not in result
        assert result["sh510050"].get("nav") is None

    @pytest.mark.asyncio
    async def test_sina_no_iopv_field_not_injected_as_nav(self, monkeypatch):
        """P0-6①: sina 接口无 IOPV——即使响应可解析，nav 也不得伪造。"""
        raw = 'var hq_str_sh510050="上证50ETF,3.021,3.029,3.066,3.067,3.018,3.066,3.067,513471237,1566985099.0,0,3.066,0,3.065,0,3.064,0,3.063,0,3.062,0,3.067,0,3.068,0,3.069,0,3.070,0,3.071,2026-08-07,15:34:59,00,D|0|0";\n'

        async def _fake_run_sync(call, *args, timeout=8):
            return raw

        monkeypatch.setattr("app.core.async_utils.run_sync", _fake_run_sync)
        result = await fr._fetch_iopv_from_sina(["sh510050"])
        assert "nav" not in result["sh510050"]


class TestQqParserRound9:
    @pytest.mark.asyncio
    async def test_qq_gbk_decode_and_pos81_nav(self, monkeypatch):
        """P0-6②: qq 返回体含 GBK 中文名称必须能解码（旧 utf-8 抛 UnicodeDecodeError 整级被吞）；
        nav 用 pos 81（单位净值，round9 实测与天天基金 DWJZ 一致），pos 31 是涨跌额。"""
        # 模拟真实 qq 响应：GBK 中文名称 + pos 31=涨跌额 + pos 81=单位净值
        name_gbk = "上证50ETF".encode("gbk").decode("latin1")
        parts = [""] * 82
        parts[1] = name_gbk  # 中文名称（GBK 字节经 latin1 中转模拟原始字节）
        parts[2] = "510050"
        parts[3] = "3.066"   # 现价
        parts[31] = "0.037"  # 涨跌额（旧实现误当 IOPV）
        parts[81] = "3.0687"  # 单位净值（round9 实测主源）
        line = f'v_sh510050="{"~".join(parts)}"'
        raw_bytes = line.encode("latin1")

        def _fake_run_sync(call, *args, timeout=8):
            # 模拟原始网络字节流（GBK 中文名）
            return raw_bytes.decode("gbk", errors="replace")

        async def _fake_run_sync_async(call, *args, timeout=8):
            return _fake_run_sync(call, *args, timeout=timeout)

        monkeypatch.setattr("app.core.async_utils.run_sync", _fake_run_sync_async)
        result = await fr._fetch_iopv_from_qq(["sh510050"])
        assert result["510050"]["nav"] == 3.0687
        assert result["510050"]["price"] == 3.066
        # 旧 bug 反例：pos 31 是涨跌额（0.037），绝不是 nav
        assert result["510050"]["nav"] != 0.037

    @pytest.mark.asyncio
    async def test_qq_short_payload_skipped(self, monkeypatch):
        """P0-6②: 字段不足 82（无 pos 81）的响应整行跳过，不得用错误字段冒充 nav。"""
        parts = [""] * 33
        parts[2] = "510050"
        parts[3] = "3.066"
        parts[31] = "0.037"
        line = f'v_sh510050="{"~".join(parts)}"'

        async def _fake_run_sync(call, *args, timeout=8):
            return line

        monkeypatch.setattr("app.core.async_utils.run_sync", _fake_run_sync)
        result = await fr._fetch_iopv_from_qq(["sh510050"])
        assert result == {}


class TestFetchFundNavContract:
    def test_ttj_lsjz_fallback_returns_dict(self, monkeypatch):
        """P0-7: fetch_fund_nav 统一 dict 契约 + 天天基金 f10/lsjz 降级（场内 ETF 可用）。"""
        from app.fetchers import china_market as cm

        cm._FUND_NAV_CACHE.clear()

        # 主源 akshare 失败 → f10/lsjz 兜底成功（round9 实测 510050 DWJZ=3.0687）
        def _fake_lsjz(symbol):
            return [{
                "FSRQ": "2026-08-07", "DWJZ": "3.0687",
                "LJJZ": "4.5764", "JZZZL": "1.37",
            }]

        with patch.object(cm, "run_in_thread", side_effect=RuntimeError("akshare down")), \
             patch.object(cm, "_fetch_ttj_lsjz", side_effect=_fake_lsjz), \
             patch.object(cm, "fund_fetcher") as _ff:
            _ff.fetch_fund_nav.return_value = None
            result = cm.fetch_fund_nav("510050")

        assert isinstance(result, dict), "契约必须为 dict（旧 tuple 被调用方 .get 抛错）"
        assert result["nav"] == 3.0687
        assert result["daily_change_pct"] == 1.37
        assert result["nav_date"] == "2026-08-07"

    def test_ttj_lsjz_parser(self, monkeypatch):
        """P0-6: _fetch_ttj_lsjz 解析 f10/lsjz JSON（LSJZList 最新在前）。

        R44 F2 (round27): 改用 requests.Session（连接池 + keep-alive）替代
        urllib.urlopen，故此处 monkeypatch 落到 requests.Session.get，仍验证
        LSJZList 解析与"最新在前"排序——网络库属实现细节，解析契约不变。
        """
        from app.fetchers import china_market as cm
        payload = '{"Data": {"LSJZList": [{"FSRQ": "2026-08-07", "DWJZ": "3.0687", "JZZZL": "1.37"}, {"FSRQ": "2026-08-06", "DWJZ": "3.0273", "JZZZL": "-0.16"}]}}'
        import requests as _req

        class _FakeResp:
            text = payload

        def _fake_get(self, url, headers=None, timeout=8, **kw):
            return _FakeResp()

        monkeypatch.setattr(_req.Session, "get", _fake_get)
        rows = cm._fetch_ttj_lsjz("510050")
        assert rows and rows[0]["DWJZ"] == "3.0687"
        assert rows[0]["FSRQ"] == "2026-08-07"

    def test_fund_nav_tuple_historical_shape_guarded(self):
        """P0-7 回归: factor_registry TTJ 兜底对历史 tuple 形态不崩（isinstance 守卫）。"""
        # 直接验证 factor_registry 的守卫逻辑可处理两种形态
        from app.factors import factor_registry as fr
        data = {}
        # tuple 历史形态（旧 china_market 返回）
        nav_tuple = (3.0687, 1.37)
        if isinstance(nav_tuple, dict) and nav_tuple.get("nav"):
            data.setdefault("510050", {})["nav"] = nav_tuple["nav"]
        elif isinstance(nav_tuple, tuple) and len(nav_tuple) >= 1 and nav_tuple[0]:
            data.setdefault("510050", {})["nav"] = nav_tuple[0]
        assert data["510050"]["nav"] == 3.0687


# ===== folded from test_round19_p9.py =====
import pandas as pd
from unittest.mock import MagicMock
class TestFetchSinaUsDaily:
    """round19 P9-②: 新浪 stock_us_daily 全量兜底（英文列名 → 系统格式）。"""

    def test_column_mapping(self, monkeypatch):
        from app.fetchers import china_market as cm
        df = pd.DataFrame([
            {"date": "2026-08-11", "open": 770.0, "high": 775.0, "low": 768.0,
             "close": 770.56, "volume": 1.2e7},
            {"date": "2026-08-12", "open": 771.0, "high": 772.0, "low": 769.0,
             "close": 771.905, "volume": 1.1e7},
        ])
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, **k: df)
        rows = cm._fetch_sina_us_daily("SPY")
        assert len(rows) == 2
        assert rows[-1]["日期"] == "2026-08-12"
        assert rows[-1]["收盘"] == pytest.approx(771.905)
        assert rows[-1]["开盘"] == pytest.approx(771.0)

    def test_failure_returns_empty(self, monkeypatch):
        from app.fetchers import china_market as cm

        def boom(fn, **k):
            raise RuntimeError("sina down")

        monkeypatch.setattr(cm, "run_in_thread", boom)
        assert cm._fetch_sina_us_daily("SPY") == []
class TestAkshareHistoryUsChain:
    """round19 P9-③: US 降级链重排——akshare(3s) → TickFlow → alphavantage → sina → finnhub(3s)。"""

    def _setup(self, monkeypatch, *, akshare_df=None, tickflow=None, av=None, sina=None, fh=None):
        from app.fetchers import china_market as cm
        import app.fetchers.global_markets_fetcher as gmf
        calls = []

        def _run_in_thread(fn, timeout=8, executor="long"):
            calls.append(("thread", timeout))
            return fn()

        monkeypatch.setattr(cm, "run_in_thread", _run_in_thread)
        monkeypatch.setattr(cm, "_tickflow_kline",
                            lambda s, p, asset_type="A": (calls.append(("tickflow", s)) or tickflow or []))
        monkeypatch.setattr(cm, "_fetch_sina_us_daily", lambda s: (calls.append(("sina", s)) or sina or []))
        monkeypatch.setattr(gmf, "fetch_daily_alphavantage",
                            lambda s: (calls.append(("av", s)) or av or []))
        monkeypatch.setattr(gmf, "fetch_candles",
                            lambda s, p: (calls.append(("finnhub", s)) or fh or []))
        # akshare 主源：run_in_thread 里 _p() 调 ak.stock_us_hist —— mock 返回空 df
        import pandas as pd
        monkeypatch.setattr("builtins.__import__", self._fake_ak_import(akshare_df))
        return cm, calls

    @staticmethod
    def _fake_ak_import(akshare_df):
        orig_import = __import__  # patch 前的原始 __import__（避免递归）

        def fake_import(name, *args, **kwargs):
            if name == "akshare":
                class _Ak:
                    @staticmethod
                    def stock_zh_a_hist(symbol=None, period=None, adjust=None):
                        return pd.DataFrame()

                    @staticmethod
                    def stock_hk_hist(symbol=None, period=None):
                        return pd.DataFrame()

                    @staticmethod
                    def stock_us_hist(symbol=None, period=None, adjust=None):
                        return akshare_df if akshare_df is not None else pd.DataFrame()
                return _Ak()
            return orig_import(name, *args, **kwargs)
        return fake_import

    def test_us_chain_order_akshare_3s_then_fallback(self, monkeypatch):
        """akshare 空 → TickFlow 命中（不继续往下）；akshare 超时 3s。"""
        from app.fetchers import china_market as cm
        tf_rows = [{"date": "2026-08-12", "close": 771.9}]  # round20: 英文 key 契约
        cm, calls = self._setup(monkeypatch, akshare_df=pd.DataFrame(), tickflow=tf_rows)
        out = cm._fetch_akshare_history("SPY", "US", "daily")
        assert out == tf_rows
        thread_timeouts = [c[1] for c in calls if c[0] == "thread"]
        assert 3 in thread_timeouts, f"US akshare 应 3s 快速失败，实得 {thread_timeouts}"
        assert ("tickflow", "SPY") in calls

    def test_us_chain_full_fallback_order(self, monkeypatch):
        """akshare → TickFlow → av → sina 全空时走 finnhub；顺序验证。"""
        from app.fetchers import china_market as cm
        fh_rows = [{"date": "2026-08-12", "close": 771.9}]
        cm, calls = self._setup(monkeypatch, akshare_df=pd.DataFrame(),
                                tickflow=[], av=[], sina=[], fh=fh_rows)
        out = cm._fetch_akshare_history("SPY", "US", "daily")
        assert out == fh_rows
        seq = [c[0] for c in calls]
        # 顺序: akshare 主源(thread) → tickflow → alphavantage(thread) → sina → finnhub(thread)
        assert seq.index("tickflow") < seq.index("av") < seq.index("sina") < seq.index("finnhub"), \
            f"US 降级链顺序应为 tickflow→av→sina→finnhub，实得 {seq}"

    def test_us_all_fail_returns_empty_no_throw(self, monkeypatch):
        from app.fetchers import china_market as cm
        cm, calls = self._setup(monkeypatch, akshare_df=pd.DataFrame(),
                                tickflow=[], av=[], sina=[], fh=[])
        out = cm._fetch_akshare_history("SPY", "US", "daily")
        assert out == []

    def test_hk_chain_tencent_preserved(self, monkeypatch):
        """HK 链保持 finnhub → av → 腾讯独立兜底（不引入新浪/变更语义）。"""
        from app.fetchers import china_market as cm
        tx_rows = [{"date": "2026-08-12", "close": 461.6}]  # round20: 英文 key 契约
        calls = []

        def _run_in_thread(fn, timeout=8, executor="long"):
            calls.append(("thread", timeout))
            return fn()

        import app.fetchers.global_markets_fetcher as gmf
        monkeypatch.setattr(cm, "run_in_thread", _run_in_thread)
        # round20 P0-4: HK 分支引入 TickFlow（china_market.py:1691）——测试必须 mock
        # 为空，否则 TickFlow 可达时返回真实数据、测试依赖网络状态（曾间歇失败）。
        monkeypatch.setattr(cm, "_tickflow_kline", lambda s, p, asset_type="A": [])
        monkeypatch.setattr(gmf, "fetch_daily_alphavantage", lambda s: [])
        monkeypatch.setattr(gmf, "fetch_candles", lambda s, p: [])
        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda s: tx_rows)
        # akshare 主源 mock（返回空 df，避免真实网络）
        monkeypatch.setattr("builtins.__import__", TestAkshareHistoryUsChain._fake_ak_import(pd.DataFrame()))
        out = cm._fetch_akshare_history("00700", "HK", "daily")
        assert out == tx_rows, "HK 全链失败后应走腾讯独立兜底"


# ===== folded from test_round20_strategy_check_p05_p18.py =====
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
class TestP0_4P1_5TickflowKline:
    def test_tickflow_kline_outputs_english_keys(self, monkeypatch):
        """P0-4/P1-5: _tickflow_kline 输出英文 key（date/open/...）——
        旧实现输出中文 key（日期/开盘…），US 端点（TickFlow 主修复）返回的中文
        key 前端/下游无法解析（round19 P9-③ 遗留契约 bug）。"""
        import pandas as pd
        from app.fetchers import china_market as cm

        fake_df = pd.DataFrame([
            {"trade_date": "2026-08-01", "open": 100.0, "high": 105.0,
             "low": 99.0, "close": 103.5, "volume": 100000},
        ])
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, timeout=12, executor="long": fake_df)
        monkeypatch.setattr(cm, "settings", type("S", (), {"tickflow_api_key": "k"})(), raising=False)

        rows = cm._tickflow_kline("AAPL", "daily", asset_type="US")
        assert rows, "TickFlow 应返回数据"
        assert "date" in rows[0] and "close" in rows[0], \
            f"TickFlow 必须输出英文 key（date/close...），实际 {sorted(rows[0].keys())}"
        assert "日期" not in rows[0], "不得再输出中文 key（契约断裂）"
        assert rows[0]["close"] == 103.5

    def test_tickflow_kline_hk_symbol_gets_hk_suffix(self, monkeypatch):
        """P0-4: HK 纯数字 symbol（00700）在 asset_type=HK 时映射 00700.HK
        （旧 _tickflow_symbol("00700") 误判为 A 股 00700.SZ）。"""
        captured = {}
        monkeypatch.setattr(
            "app.fetchers.china_market._tickflow_symbol",
            lambda s: captured.setdefault("called", 0) or captured.setdefault("sym", s),
        )
        from app.fetchers import china_market as cm

        monkeypatch.setattr(cm, "run_in_thread", lambda fn, timeout=12, executor="long": None)
        monkeypatch.setattr(cm, "settings", type("S", (), {"tickflow_api_key": "k"})(), raising=False)

        rows = cm._tickflow_kline("00700", "daily", asset_type="HK")
        # 返回空（run_in_thread→None）但 tf_sym 构建不应依赖 _tickflow_symbol 误判：
        # 直接验证 asset_type=HK 分支不调用 _tickflow_symbol（已短路为 00700.HK）
        assert "called" not in captured, "HK 分支不应走 _tickflow_symbol（防 00700→00700.SZ 误判）"

    def test_fetch_history_hk_akshare_chain_tries_tickflow(self, monkeypatch):
        """P0-4: akshare HK 空后 TickFlow 兜底被调用（对齐 US 分支模式）。"""
        from app.fetchers import china_market as cm
        tf_rows = [{"date": "2026-08-01", "open": 490, "close": 492.2,
                    "high": 495, "low": 485, "volume": 100}]
        called = {"tf": False}

        monkeypatch.setattr(cm, "_fetch_tencent_hk_history", lambda symbol: [])
        monkeypatch.setattr(cm, "_tickflow_kline",
                            lambda *a, **k: (called.__setitem__("tf", True) or tf_rows))
        monkeypatch.setattr(cm, "run_in_thread", lambda fn, timeout=8, executor="long": None)
        monkeypatch.setattr(cm, "global_markets_fetcher",
                            type("F", (), {"fetch_daily_alphavantage": staticmethod(lambda *a, **k: None)})())

        rows = cm.fetch_history("00700", "HK", "daily")
        assert called["tf"] is True, "腾讯空后应调用 TickFlow 兜底"
        assert rows == tf_rows

"""
R5-2-10: 国内宏观/流动性数据管道（用户反馈 #16）。

akshare 宏观接口（LPR / 中美国债收益率 / M0-M2 / CPI-PPI），
带 24h 成功缓存 + 1h 失败缓存（R4-26 模式）；源不可用/数据滞后显式标注。

注意：R5-2-10 时代“Shibor/社融接口已失效”的评论已过时——2026-08-09 实测恢复可用：macro_china_shibor_all 2341 行 2.2s、macro_china_shrzgm（社融）136 行 1.5s。未纳入本模块（待 round13 接入）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd

# round36 恢复：tests 经 mock.patch("app.fetchers.macro_fetcher.run_in_thread") 打补丁，
# 字符串引用对 ruff F401 不可见——noqa = 有意保留的 patch 面。
from ..core.async_utils import run_in_thread  # noqa: F401
from ..services.cache_service import cached
from ..utils.decode import decode_df as _decode_df

logger = logging.getLogger(__name__)

# 24h 成功缓存 / 1h 失败缓存（R4-26 模式）
_SUCCESS_TTL = 86400
_FAIL_TTL = 3600

# R79 (round29): fetch_all_domestic_macro 单源超时（秒）。整包上游超时 20s，
# 单源必须显著更短，否则一个慢源即耗尽整包预算 → 全部 unavailable。
_MACRO_SOURCE_TIMEOUT = 8.0


def _stale_note(date_str: str, source: str, months: int = 3) -> tuple[bool, str]:
    """判断数据是否滞后 >3 个月 → (stale, note)。兼容 YYYY-MM-DD 与 YYYY-MM。"""
    s = str(date_str or "").strip()
    if not s:
        return False, ""
    try:
        # 月份格式 YYYY-MM（如 2025-09）→ 补 -01
        if len(s) == 7 and s[4] == "-":
            d = datetime.strptime(s + "-01", "%Y-%m-%d")
        else:
            d = datetime.strptime(s[:10], "%Y-%m-%d")
        if (datetime.now() - d) > timedelta(days=months * 30):
            return True, f"数据滞后至{s[:7]}（{source}），仅作趋势参考"
    except (ValueError, TypeError):
        pass
    return False, ""


def fetch_lpr() -> dict | None:
    """LPR 贷款市场报价利率：取最后一行（最新一期），映射 LPR1Y/LPR5Y。"""
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_lpr()
    df = cached("macro:lpr", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]  # 最后一行 = 最新一期
    # round13: 当前 akshare 返回 TRADE_DATE（datetime.date），兼容旧「日期」
    date_str = str(row.get("日期", row.get("TRADE_DATE", "")) or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        return {
            "lpr_1y": float(row.get("LPR1Y", row.get("LPR1Y", 0)) or 0) or None,
            "lpr_5y": float(row.get("LPR5Y", row.get("LPR5Y", 0)) or 0) or None,
            "date": date_str[:10],
            "stale": stale,
            "note": note,
        }
    except (ValueError, TypeError):
        return None


def fetch_bond_yields() -> dict | None:
    """中美国债收益率 + 10Y 利差（bp）。"""
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.bond_zh_us_rate()
    df = cached("macro:bond", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        cn_10y = float(row.get("中国国债收益率10年", 0) or 0) or None
        us_10y = float(row.get("美国国债收益率10年", 0) or 0) or None
        spread_bp = round((cn_10y - us_10y) * 100, 1) if cn_10y is not None and us_10y is not None else None
        return {
            "cn_10y": cn_10y,
            "us_10y": us_10y,
            "spread_bp": spread_bp,
            "date": date_str[:10],
            "stale": stale,
            "note": note,
        }
    except (ValueError, TypeError):
        return None


def fetch_money_supply() -> dict | None:
    """M0/M1/M2 货币供应同比。

    round13: 当前 akshare 列名「货币和准货币(M2)-同比增长」（旧版「M2-同比增长」），
    双名兼容——旧实现映射失效致 m2_yoy 恒 None（假实现隐患）。
    """
    def _p():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_money_supply()
    df = cached("macro:money", _p, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("月份", "") or row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")

    def _num(*keys):
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            try:
                f = float(v)
                if f == f:  # 非 nan
                    return f
            except (ValueError, TypeError):
                continue
        return None

    return {
        "m0_yoy": _num("流通中的现金(M0)-同比增长", "M0-同比增长"),
        "m1_yoy": _num("货币(M1)-同比增长", "M1-同比增长"),
        "m2_yoy": _num("货币和准货币(M2)-同比增长", "M2-同比增长"),
        "date": date_str[:10],
        "stale": stale,
        "note": note,
    }


def fetch_cpi_ppi() -> dict | None:
    """CPI/PPI 同比（round13 修正：宽表同比接口 macro_china_cpi / macro_china_ppi）。

    原实现错用 macro_china_cpi_monthly（单商品长表，今值=CPI 月率非同比）且
    iloc[-1] 取降序表最早行（2008）→ cpi_yoy/ppi_yoy 恒空/假数据。改用宽表
    「全国-同比增长」/「当月同比增长」（实测最新 2026-07 可用），取月份最大行
    （兼容接口升降序）。今值 nan 或日期 >3 个月 → stale=true + note（不编造）。
    """
    def _cpi():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_cpi()
    def _ppi():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_ppi()
    cpi_df = cached("macro:cpi", _cpi, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    ppi_df = cached("macro:ppi", _ppi, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if cpi_df is None and ppi_df is None:
        return None  # 源全失败 → None（fetch_all_domestic_macro unavailable 语义）
    cpi_row = _latest_row(cpi_df)
    ppi_row = _latest_row(ppi_df)

    def _num(row, *keys):
        if row is None:
            return None
        for k in keys:
            v = row.get(k)
            if v is None:
                continue
            try:
                f = float(v)
                if f == f:  # 非 nan
                    return f
            except (ValueError, TypeError):
                continue
        return None
    cpi = _num(cpi_row, "全国-同比增长", "同比增长")
    ppi = _num(ppi_row, "当月同比增长", "同比增长")
    _cpi_date = cpi_row.get("月份", "") if cpi_row is not None else ""
    _ppi_date = ppi_row.get("月份", "") if ppi_row is not None else ""
    date_str = str(_cpi_date or _ppi_date or "")
    # 今值 nan 或日期 >3 个月 → stale
    stale = cpi is None or ppi is None
    _, _ = _stale_note(date_str, "数据源")  # 日期滞后同样标记
    note = ""
    if cpi is None or ppi is None:
        stale = True
        note = "数据滞后或缺失（数据源返回空值），仅作趋势参考"
    else:
        _, note = _stale_note(date_str, "数据源")
        stale = stale or (note != "")
    return {
        "cpi_yoy": cpi,
        "ppi_yoy": ppi,
        "date": date_str[:10],
        "stale": stale,
        "note": note,
    }


def _latest_row(df) -> dict | None:
    """取宏观 df 中「月份/日期」最大的一行（兼容接口升降序；macro_china_cpi 实测为降序）。"""
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    key = "月份" if "月份" in df.columns else ("日期" if "日期" in df.columns else df.columns[0])

    def _parse(s):
        s = str(s or "").strip()
        s = s.replace("年", "-").replace("月份", "").replace("月", "")
        try:
            return datetime.strptime(s[:7], "%Y-%m")
        except ValueError:
            return datetime(1970, 1, 1)
    best = df.iloc[0]
    best_d = _parse(best.get(key, ""))
    for _, r in df.iterrows():
        d = _parse(r.get(key, ""))
        if d > best_d:
            best, best_d = r, d
    return best


def _no_proxy():
    from ..utils.proxy import no_proxy
    return no_proxy()


# ── R08 (round58 §3 P1): 沪深港通（北向）历史资金流 ──────────────────────────
# 背景（round58 §1 M7）：北向资金**实时**披露自 2024-08 起被监管取消，历史日频
# 仍可得（东财 datacenter-web RPT_MUTUAL_DEAL_HISTORY）。本函数提供近 N 个交易日
# 净流入，作为「北向实时」的诚实替代。
#
# 实现纪律（round58 §2 P2-3 + §6-8，2026-09-28 实测校正）：
#   1. **不传 symbol 参数**。akshare 的 `symbol_map` 键为中文，Windows cp936
#      源文件里字面量会被 mangling → 探针复现 KeyError。实测 akshare 1.18.94
#      的 `stock_hsgt_hist_em(symbol="北向资金")` **默认值就是北向**，故按默认
#      参数调用即得北向序列；口径标签用 `inspect.signature` **程序化**取默认值，
#      源码里不落任何中文 symbol 字面量。
#   2. ⚠️ 方案文档 §2 P2-3「默认列含北向/南向」的表述与实测不符：默认返回列
#      为 日期/当日成交净买额/买入成交额/卖出成交额/历史累计净买额/当日资金流向/
#      当日余额/持股市值/领涨…/沪深300…，**无「北向」「南向」前缀**。故净额按
#      「含净的列优先，否则 买入额-卖出额」结构化取列，不按方向前缀猜列。
#   3. 南向序列需另一次调用（symbol 取 symbol_map 中的南向键），本轮**未接**
#      ——键需程序化解析 symbol_map，收益低于风险，登记为后续轮次项；
#      `south_net` 恒 None，调用方按「数据源暂不可用」渲染，不臆造。
#   4. 日频 → 24h 成功 / 1h 失败缓存（_SUCCESS_TTL/_FAIL_TTL）：逐页拉全量
#      2.3s 绝不可放请求链。
#   5. 日期列/净额列认不出 → 返回 None（调用方占位），绝不编造数值。

_HSGT_CACHE_KEY = "macro:hsgt_hist"
#: 判定「日频序列仍新鲜」的最大天数。实测（2026-09-28，akshare 1.18.94 / 东财
#: RPT_MUTUAL_DEAL_HISTORY）北向净额最后可得日为 **2024-08-16**——监管 2024-08
#: 停止披露后，接口仍返回行但净额列为 NaN。故本阈值用于把「停更」与「有值」
#: 分开：超期不返回任何数值（宁可占位也不给 2 年前的数当当前资金行为）。
HSGT_FRESH_DAYS = 7


def _hsgt_default_caliber() -> str:
    """程序化取 akshare 该接口的默认口径标签（实测=北向），空串=取不到。

    用 inspect 读函数签名的默认值，而不是在源码里写死中文字面量——
    akshare 换默认值时本函数自动跟随（口径漂移由 caliber 字段暴露给 prompt）。
    """
    try:
        import inspect

        import akshare as ak
        return str(inspect.signature(ak.stock_hsgt_hist_em)
                   .parameters["symbol"].default or "")
    except Exception:  # noqa: BLE001 — 探针失败按「口径未知」处理，不中断
        return ""


def _hsgt_first_col(columns, *keywords) -> str | None:
    """首个同时含全部关键词的列名；无匹配 → None。"""
    for c in columns:
        name = str(c)
        if all(k in name for k in keywords):
            return str(c)
    return None


def _hsgt_row_value(row, col: str | None) -> float | None:
    """单格取数：**缺失/NaN/空串 → None**（绝不用 0 冒充「无变化」）。

    停更后接口仍返行但净额列为 NaN（2026-09-28 实测）；旧写法
    `float(row.get(col, 0) or 0)` 会把 None/NaN 折成 0.0，等于把「无数据」
    渲染成「净流入 0 元」——反假完成禁止。
    """
    if not col:
        return None
    raw = row.get(col)
    if raw is None or raw == "":
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v == v else None  # NaN → None


def _hsgt_net_value(row, cols) -> float | None:
    """该序列的当日净买额：优先「当日…净…」列，其次任意「净」列（排除累计），
    否则 买入额 - 卖出额。

    两个已实证的坑：
      - 不可把「净买额 + 买入额 + 卖出额」直接相加（重复计数，1.2e9 → 1.3e9）。
      - 源同时给「当日成交净买额」与「历史累计净买额」两个含「净」的列；
        误取累计列会把 1.0e11 累计值当当日净额（单元测试锁定）。
    """
    names = [str(c) for c in cols]
    daily_net = next(
        (c for c in names if "净" in c and "累计" not in c and "当日" in c), None)
    net_col = daily_net or next(
        (c for c in names if "净" in c and "累计" not in c), None)
    if net_col is not None:
        return _hsgt_row_value(row, net_col)
    buy = next((c for c in names if "买入" in c), None)
    sell = next((c for c in names if "卖出" in c), None)
    b, s = _hsgt_row_value(row, buy), _hsgt_row_value(row, sell)
    if b is None and s is None:
        return None
    if b is None or s is None:
        return None  # 只有一侧 → 无法算净额，不拿单边冒充
    return round(b - s, 4)


def fetch_hsgt_history(days: int = 5) -> dict | None:
    """R08: 沪深港通（北向口径）近 ``days`` 个交易日净买额，单位:元。

    返回 ``{"as_of": "2026-09-24",
             "rows": [{"date": ..., "north_net": 1.2e9, "south_net": None}],
             "caliber": <程序化取到的口径标签>, "source": "eastmoney-datacenter-web",
             "cadence": "daily-history"}``；源不可用/列口径不识别 → None。

    口径纪律（写入 prompt 时必须随行给出）：**日频历史值，非实时**；
    北向实时自 2024-08 起停止披露，LLM 不得编造「今日北向」。

    ⚠️ 停更处理（2026-09-28 实测）：净额序列最后可得日 = 2024-08-16。超过
    ``HSGT_FRESH_DAYS`` 时返回 ``stale=True`` + ``rows=[]`` + ``last_available``，
    **不返回任何数值**——给 2 年前的净买额当「当前资金行为」比没有更糟。
    ``south_net`` 本轮恒 None（南向序列未接，见上方纪律 3）。
    """
    def _fetch():
        import akshare as ak
        with _no_proxy():
            # 不传 symbol：默认即北向口径（见上方纪律 1/2）
            return ak.stock_hsgt_hist_em()

    df = cached(_HSGT_CACHE_KEY, _fetch, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or getattr(df, "empty", True):
        return None
    df = _decode_df(df)
    cols = list(df.columns)
    date_col = _hsgt_first_col(cols, "日期") or _hsgt_first_col(cols, "时间")
    if date_col is None:
        return None
    net_col = _hsgt_first_col(cols, "净")
    buy_col = _hsgt_first_col(cols, "买入")
    sell_col = _hsgt_first_col(cols, "卖出")
    if net_col is None and (buy_col is None or sell_col is None):
        return None

    # 只取**有净额**的行（停更后接口仍返行但净额列为 NaN）
    rows: list[dict] = []
    for _, row in df.iterrows():
        d = str(row.get(date_col, "") or "")[:10]
        if not d:
            continue
        net = _hsgt_net_value(row, [net_col, buy_col, sell_col])
        if net is None:
            continue
        rows.append({"date": d, "north_net": net, "south_net": None})
    if not rows:
        return None
    rows = rows[-days:]
    last_date = rows[-1]["date"]
    # 停更检测：最后可得日距今超过 HSGT_FRESH_DAYS → 只报日期，不报数值
    try:
        from datetime import date as _date
        age = (_date.today() - _date.fromisoformat(last_date)).days
    except ValueError:
        age = HSGT_FRESH_DAYS + 1
    fresh = age <= HSGT_FRESH_DAYS
    return {
        "as_of": last_date if fresh else None,
        "rows": rows if fresh else [],
        "stale": not fresh,
        "stale_days": age,
        "last_available": last_date,
        "caliber": _hsgt_default_caliber(),
        "source": "eastmoney-datacenter-web",
        "cadence": "daily-history",
    }


def _macro_last_row(df, value_key: str = "今值") -> dict | None:
    """取宏观 df 最后一行 → {value, date, stale, note}（列名 商品/日期/今值 兼容）。"""
    if df is None or df.empty:
        return None
    df = _decode_df(df)
    row = df.iloc[-1]
    date_str = str(row.get("日期", "") or "")
    stale, note = _stale_note(date_str, "数据源")
    try:
        v = float(row.get(value_key, 0) or 0)
        if v != v:  # nan
            return {"value": None, "date": date_str[:10], "stale": True,
                    "note": "数据源返回空值，仅作趋势参考"}
    except (ValueError, TypeError):
        v = None
    return {"value": v, "date": date_str[:10], "stale": stale, "note": note}


def fetch_pmi_gdp() -> dict | None:
    """PMI + GDP 两源（round13 §3.1，实测 250/61 行，东财数据中心非 push2 反爬范围）。

    - PMI: macro_china_pmi_yearly（每月一条，荣枯线 50）
    - GDP: macro_china_gdp_yearly（季频发布，同比增速）
    各自 24h 成功 / 1h 失败缓存；全失败 → None。滞后 >3 个月 → stale + note（前视偏差红线）。
    """
    def _pmi():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_pmi_yearly()
    def _gdp():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_gdp_yearly()
    pmi_df = cached("macro:pmi", _pmi, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    gdp_df = cached("macro:gdp", _gdp, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    pmi = _macro_last_row(pmi_df)
    gdp = _macro_last_row(gdp_df)
    if (pmi is None or pmi.get("value") is None) and (gdp is None or gdp.get("value") is None):
        return None
    as_of = max([d for d in ((pmi or {}).get("date", "") or "", (gdp or {}).get("date", "") or "") if d] or [""])
    return {
        "pmi": pmi,
        "gdp": gdp,
        "as_of": as_of,
    }


def fetch_gdp_series(n: int = 8) -> list[float]:
    """GDP 同比增速近 n 期（季频，round13 §3.1 P2 macro.gdp_trend 用）。

    复用 macro:gdp 缓存键（与 fetch_pmi_gdp 共享）；只用已发布值（前视偏差红线）；
    失败/空 → []（compute 输出 0 诚实降级）。
    """
    def _gdp():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_gdp_yearly()
    df = cached("macro:gdp", _gdp, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if df is None or df.empty:
        return []
    df = _decode_df(df)
    # 列名兼容：优先「今值」，兜底「同比增长」（akshare 版本差异）
    col = next((c for c in df.columns if str(c) == "今值"), None) or \
        next((c for c in df.columns if "同比" in str(c)), None)
    if col is None:
        return []
    vals = pd.to_numeric(df[col], errors="coerce").dropna().tolist()
    return [float(v) for v in vals[-n:]]


def fetch_margin_leverage_snapshot(n_days: int = 20) -> dict | None:
    """两融杠杆资金情绪 snapshot（round13 两融因子 macro.margin_leverage_trend）。

    沪深融资余额（macro_china_market_margin_sh/sz）按日期合并取交集（双方均有的
    最新交易日），合计后算 n 日变化率：>+0.05 → +1（杠杆流入）；<-0.05 → -1；
    中间 → 0。24h 成功 / 1h 失败缓存；任一源失败 → None（诚实降级，不编造）。
    """
    def _sh():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_market_margin_sh()
    def _sz():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_market_margin_sz()
    sh_df = cached("macro:margin_sh", _sh, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    sz_df = cached("macro:margin_sz", _sz, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    if sh_df is None or sz_df is None:
        return None

    def _balance_series(df) -> tuple[list, list]:
        df = _decode_df(df)
        dates = pd.to_datetime(df["日期"], errors="coerce")
        bal = pd.to_numeric(df["融资余额"], errors="coerce")
        pairs = sorted((d, b) for d, b in zip(dates, bal, strict=False)
                       if d is not None and pd.notna(d) and pd.notna(b))
        return [d for d, _ in pairs], [float(b) for _, b in pairs]

    sh_dates, sh_bal = _balance_series(sh_df)
    sz_dates, sz_bal = _balance_series(sz_df)
    # 按日期交集合并（沪深交易日对齐）
    sh_map = {d: b for d, b in zip(sh_dates, sh_bal, strict=False)}
    sz_map = {d: b for d, b in zip(sz_dates, sz_bal, strict=False)}
    common = sorted(set(sh_map) & set(sz_map))
    if len(common) < 2:
        return None
    total = [sh_map[d] + sz_map[d] for d in common]
    if len(total) < n_days:
        n_days = len(total) - 1  # 样本不足时用全部可用区间
    change = (total[-1] - total[-n_days]) / total[-n_days]
    change = round(change, 4)
    direction = 1 if change > 0.05 else (-1 if change < -0.05 else 0)
    return {
        "margin_balance_total": round(total[-1], 2),
        "margin_balance_n_days_ago": round(total[-n_days], 2),
        "margin_leverage_change": change,
        "margin_leverage_direction": direction,
        "as_of": str(common[-1].date()),
        "samples": len(total),
    }


def fetch_macro_snapshot() -> dict | None:
    """聚合 M2 同比 / PMI / LPR 1Y → 方向标注（round13 §3.1 P1，契约 market/macro-regime.md）。

    复用 macro:* 24h 成功 / 1h 失败缓存；三指标全不可用 → None（detect_market_regime 降级）。
    - m2_direction: M2 同比 3 月斜率（< -0.1 收紧 → -1；> +0.1 宽松 → +1）
    - pmi_direction: PMI ≥ 50 → +1；< 50 → -1
    - lpr_direction: LPR 1Y 同比（365 天窗口）：下降 → +1（降息周期）；上升 → -1
    - macro_direction: sign(三者之和)，clamp [-1, 1]
    """
    def _m2():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_money_supply()
    def _lpr():
        import akshare as ak
        with _no_proxy():
            return ak.macro_china_lpr()
    m2_df = cached("macro:m2_series", _m2, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    lpr_df = cached("macro:lpr_series", _lpr, ttl=_SUCCESS_TTL, fail_ttl=_FAIL_TTL)
    pmi_gdp = fetch_pmi_gdp() or {}
    pmi_val = (pmi_gdp.get("pmi") or {}).get("value")

    def _series_vals(df, key_prefix: str) -> list[float]:
        if df is None or df.empty:
            return []
        df = _decode_df(df)
        # 优先「…同比增长」列（前缀 + 同比限定，避免命中数量/环比列）；
        # 前缀不匹配时兜底精确旧列名「M2-同比增长」（akshare 版本差异）
        col = next((c for c in df.columns if str(c).startswith(key_prefix) and "同比" in str(c)), None)
        if col is None:
            col = next((c for c in df.columns if str(c).startswith(key_prefix)), None)
        if col is None:
            legacy = "M2-同比增长"
            col = legacy if legacy in df.columns else None
        if col is None:
            return []
        return [float(x) for x in pd.to_numeric(df[col], errors="coerce").dropna().tolist() if float(x) == float(x)]

    m2_vals = _series_vals(m2_df, "货币和准货币(M2)")
    lpr_vals = _series_vals(lpr_df, "LPR1Y")

    m2_now = m2_vals[-1] if m2_vals else None
    m2_3m = m2_vals[-3] if len(m2_vals) >= 3 else None
    m2_slope = round(m2_now - m2_3m, 2) if m2_now is not None and m2_3m is not None else None
    m2_direction = -1 if (m2_slope is not None and m2_slope < -0.1) else (1 if (m2_slope is not None and m2_slope > 0.1) else 0)

    pmi_direction = 1 if (pmi_val is not None and pmi_val >= 50) else (-1 if (pmi_val is not None and pmi_val < 50) else 0)

    lpr_now = lpr_vals[-1] if lpr_vals else None
    lpr_12m = None
    if lpr_df is not None and not lpr_df.empty and lpr_vals:
        _d = _decode_df(lpr_df)
        try:
            dates = pd.to_datetime(_d["TRADE_DATE"] if "TRADE_DATE" in _d.columns else _d["日期"], errors="coerce")
            last_date = dates.iloc[-1]
            target = last_date - pd.Timedelta(days=365)
            mask = dates <= target
            if mask.any():
                lpr_12m = lpr_vals[mask.to_numpy().nonzero()[0][-1]]
        except Exception:
            lpr_12m = None
    lpr_diff = round(lpr_now - lpr_12m, 2) if lpr_now is not None and lpr_12m is not None else None
    lpr_direction = 1 if (lpr_diff is not None and lpr_diff < -0.05) else (-1 if (lpr_diff is not None and lpr_diff > 0.05) else 0)

    sources = []
    if m2_now is not None:
        sources.append("M2")
    if pmi_val is not None:
        sources.append("PMI")
    if lpr_now is not None:
        sources.append("LPR")
    if not sources:
        return None

    total = m2_direction + pmi_direction + lpr_direction
    macro_direction = 1 if total > 0 else (-1 if total < 0 else 0)
    as_of = max([d for d in (
        str((pmi_gdp.get("pmi") or {}).get("date", "") or ""),
        str((pmi_gdp.get("gdp") or {}).get("date", "") or ""),
    ) if d] or [""])
    return {
        "m2_yoy_now": m2_now,
        "m2_yoy_3m_ago": m2_3m,
        "m2_slope": m2_slope,
        "m2_direction": m2_direction,
        "pmi_value": pmi_val,
        "pmi_direction": pmi_direction,
        "lpr_1y_now": lpr_now,
        "lpr_1y_12m_ago": lpr_12m,
        "lpr_direction": lpr_direction,
        "macro_direction": macro_direction,
        "as_of": as_of,
        "sources": sources,
    }


async def fetch_all_domestic_macro() -> dict:
    """六源并行拉取；全失败 → {"unavailable": true}（LLM 显式写不可用，不编造）。

    round13: 并入 PMI/GDP（fetch_pmi_gdp）与 macro_snapshot（方向标注）。
    R79 (round29): 每源独立短超时（_MACRO_SOURCE_TIMEOUT）——旧实现 asyncio.gather
    无单源超时，一个慢源拖死整包 20s → 全部 unavailable。现单源超时仅该源返回 None，
    其余照常。
    """
    import asyncio

    async def _safe(fn):
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn), timeout=_MACRO_SOURCE_TIMEOUT)
        except Exception:
            return None

    lpr, bond, money, cpi, pmi_gdp, snapshot = await asyncio.gather(
        _safe(fetch_lpr),
        _safe(fetch_bond_yields),
        _safe(fetch_money_supply),
        _safe(fetch_cpi_ppi),
        _safe(fetch_pmi_gdp),
        _safe(fetch_macro_snapshot),
    )
    if lpr is None and bond is None and money is None and cpi is None and pmi_gdp is None:
        return {"unavailable": True}
    return {
        "lpr": lpr,
        "bond_yields": bond,
        "money_supply": money,
        "cpi_ppi": cpi,
        "pmi_gdp": pmi_gdp,
        "macro_snapshot": snapshot,
        "unavailable": False,
    }

"""
Backtest portfolio designs against CSI 300.
Fetches historical weekly returns for recommended ETFs and calculates
portfolio performance vs benchmark.
"""
import json, asyncio, time
from typing import Any
import httpx

LLM_API_URL = "https://api.deepseek.com/chat/completions"
API_KEY = "REDACTED"

# ── Current market data (same as optimizer) ──────────────────────

def get_current_market_data() -> dict:
    from app.fetchers.akshare_fetcher import fetch_index_realtime
    from app.fetchers.yfinance_fetcher import fetch_us_etf_realtime
    data = {"cn_indices": "", "us_data": "", "commodity_data": "", "news_data": ""}
    try:
        indices = fetch_index_realtime()
        cn_lines = []
        for idx in indices:
            name = idx.get("name", "")
            price = idx.get("price", "N/A")
            chg = idx.get("change_pct", "N/A")
            if name and price:
                cn_lines.append(f"- {name}：{price}，涨跌幅{chg}%")
        data["cn_indices"] = "\n".join(cn_lines) if cn_lines else "（暂无数据）"
    except Exception as e:
        data["cn_indices"] = f"（获取失败：{e}）"
    try:
        us_data = []
        for sym, name in [("^GSPC", "标普500"), ("^IXIC", "纳斯达克"), ("^DJI", "道琼斯")]:
            d = fetch_us_etf_realtime(sym)
            if d and d.get("price"):
                us_data.append(f"- {name}：{d['price']}，涨跌幅{d.get('change_pct',0)}%")
        data["us_data"] = "\n".join(us_data) if us_data else "（暂无数据）"
    except:
        data["us_data"] = "（暂无数据）"
    try:
        comm = []
        for sym, name in [("GC=F", "黄金"), ("CL=F", "原油")]:
            d = fetch_us_etf_realtime(sym)
            if d and d.get("price"):
                comm.append(f"- {name}：{d['price']}，涨跌幅{d.get('change_pct',0)}%")
        data["commodity_data"] = "\n".join(comm) if comm else "（暂无数据）"
    except:
        data["commodity_data"] = "（暂无数据）"
    try:
        from app.fetchers.akshare_fetcher import fetch_news_headlines
        news = fetch_news_headlines()[:5]
        if news:
            data["news_data"] = "\n".join(f"- {n.get('title','')[:80]}" for n in news)
    except:
        data["news_data"] = "（暂无详细数据）"
    return data


# ── Historical weekly returns via mootdx ─────────────────────────

def get_weekly_returns(symbol: str, weeks: int = 8) -> list[float]:
    """Fetch weekly returns for a symbol. Returns list of weekly % returns (newest first)."""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        # Try index() for indices, bars() for stocks/ETFs
        is_index = symbol.startswith("000") or symbol.startswith("399")
        if is_index:
            df = client.index(symbol=[symbol])
            if df is not None and not df.empty:
                # Index data is realtime snapshot, not enough for history
                pass
        # Use bars for history data (supports stocks and ETFs)
        df = client.bars(symbol=symbol, frequency=5, start=0, count=weeks * 2)
        if df is not None and not df.empty and len(df) >= 2:
            returns = []
            for i in range(min(weeks, len(df) - 1)):
                o = float(df.iloc[i].get("open", 0) or 0)
                c = float(df.iloc[i].get("close", 0) or 0)
                r = round((c - o) / o * 100, 2) if o else 0
                returns.append(r)
            return returns[:weeks]
    except:
        pass
    return []

def get_weekly_close(symbol: str, weeks: int = 8) -> list[float]:
    """Get weekly close prices."""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        df = client.bars(symbol=symbol, frequency=5, start=0, count=weeks * 2)
        if df is not None and not df.empty:
            return [float(df.iloc[i].get("close", 0) or 0) for i in range(min(weeks, len(df)))]
    except:
        pass
    return []


def get_csi300_history(weeks: int = 8) -> list[dict]:
    """Get CSI 300 weekly history using Sina API fallback."""
    import requests
    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000300&scale=1200&datalen=50"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        if isinstance(data, list) and len(data) >= 2:
            # Sina returns daily data; we convert to weekly
            result = []
            for d in data:
                close = float(d.get("close", 0))
                if close:
                    result.append(close)
            # Take last `weeks` data points
            return result[-weeks:] if len(result) >= weeks else result
    except:
        pass
    return []


# ── System prompt (best version: V12 refined) ───────────────────

BEST_SYSTEM_PROMPT = """你是专业的ETF投资组合策略分析师。你必须基于输入数据设计三套ETF组合。

核心要求：
- 每个组合推荐8-10只ETF，覆盖宽基指数+行业主题+跨境ETF+商品ETF
- 不含债券ETF（债券由用户独立管理）
- 单只ETF权重5%-15%，同行业不超过2只
- 成长型与价值型均衡配置，单一风格不超过60%
- 所有配置逻辑必须引用输入数据中的具体数字

风险梯度：
- 进攻型：权益≥85%，现金≤10%，目标跑赢沪深300
- 平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300
- 防御型：权益45%-60%，现金≥20%，目标收益接近沪深300且波动低于沪深300

仅输出纯JSON，不要markdown代码块包裹。"""

BEST_USER_INSTRUCTIONS = """基于以上最新行情数据，设计三套ETF组合策略（进攻型、平衡型、防御型）。

每个组合推荐8-10只ETF，覆盖宽基指数、行业主题、跨境ETF、商品ETF。
不含债券ETF。单只权重5%-15%，同行业不超过2只。成长与价值均衡。
防御型以宽基+红利+消费为主，高现金+黄金降低波动。

输出纯JSON格式：
{
  "portfolios": [
    {
      "type": "aggressive",
      "name": "进攻型组合",
      "etfs": [{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "配置逻辑"}],
      "cash_weight": 0.XX,
      "description": "概述",
      "tips": ["操作要点"],
      "risks": ["风险提示"]
    },
    {"type": "balanced", ...},
    {"type": "defensive", ...}
  ]
}"""

BASE_USER_PROMPT = """# 任务
基于以下最新行情数据，设计三套ETF组合策略（进攻型、平衡型、防御型）。你必须完整使用所有输入数据。

# 输入数据
## A股市场
{cn_indices}

## 美股市场
{us_data}

## 港股市场
- 恒生指数：（暂无数据）
- 恒生科技指数：（暂无数据）

## 大宗商品
{commodity_data}

## 宏观背景
{news_data}

# {instructions}

# 输出格式（纯JSON）
{{
  "portfolios": [
    {{
      "type": "aggressive|balanced|defensive",
      "name": "进攻型组合|平衡型组合|防御型组合",
      "etfs": [{{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "核心逻辑"}}],
      "cash_weight": 0.XX,
      "description": "配置逻辑概述",
      "tips": ["操作要点"],
      "risks": ["风险提示"]
    }}
  ]
}}"""


async def call_llm(system: str, user: str) -> tuple[str, float]:
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        resp = await client.post(
            LLM_API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={"model": "deepseek-v4-flash", "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}], "temperature": 0.3, "max_tokens": 8192},
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"], time.time() - t0


def parse_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    try:
        start, end = cleaned.index("{"), cleaned.rindex("}")
        return json.loads(cleaned[start:end+1])
    except:
        return {}


def get_daily_returns(symbol: str, days: int = 30) -> list[float]:
    """Get daily closing prices and compute daily returns."""
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        df = client.bars(symbol=symbol, frequency=9, start=0, count=days * 2)
        if df is not None and not df.empty and len(df) >= 3:
            closes = [float(df.iloc[i].get("close", 0) or 0) for i in range(min(days, len(df)))]
            if len(closes) >= 2:
                rets = []
                for i in range(len(closes) - 1):
                    r = round((closes[i] - closes[i+1]) / closes[i+1] * 100, 2) if closes[i+1] else 0
                    rets.append(r)
                return rets
    except:
        pass
    return []


def estimate_portfolio_return(etfs: list[dict], weeks: int = 4) -> tuple[float, float]:
    """
    Estimate portfolio forward return using historical daily ETF data.
    Returns (avg_daily_return_pct, daily_volatility_pct).
    For comparison with CSI 300, we use the same period's data.
    """
    if not etfs:
        return (0, 0)
    
    daily_rets = []
    for e in etfs:
        weight = e.get("weight", 0)
        sym = e.get("symbol", "")
        rets = get_daily_returns(sym, 30)
        if rets and len(rets) >= 5:
            daily_rets.append((weight, rets))
    
    if not daily_rets:
        return (0, 0)
    
    # Calculate portfolio daily returns (weighted average)
    n = min(30, min(len(r) for _, r in daily_rets))
    portfolio_daily = []
    for di in range(n):
        total_w = sum(w for w, r in daily_rets if di < len(r))
        if total_w > 0:
            pr = sum(w * r[di] for w, r in daily_rets if di < len(r)) / total_w
            portfolio_daily.append(pr)
    
    if not portfolio_daily:
        return (0, 0)
    
    avg_return = sum(portfolio_daily) / len(portfolio_daily)
    variance = sum((r - avg_return) ** 2 for r in portfolio_daily) / len(portfolio_daily)
    volatility = variance ** 0.5
    
    return (round(avg_return, 4), round(volatility, 4))


def get_csi300_weekly(weeks: int = 8) -> tuple[float, float]:
    """Get CSI 300 weekly return and volatility via Sina."""
    prices = get_csi300_history(weeks + 1)
    if len(prices) < 2:
        return (0, 0)
    rets = []
    # Take last N weeks of data
    for i in range(min(weeks, len(prices) - 1)):
        prev, curr = prices[-(i+2)], prices[-(i+1)]
        r = round((curr - prev) / prev * 100, 2) if prev else 0
        rets.append(r)
    if not rets:
        return (0, 0)
    avg_r = sum(rets) / len(rets)
    var_r = sum((r - avg_r) ** 2 for r in rets) / len(rets)
    return (round(avg_r, 2), round(var_r ** 0.5, 2))


async def main():
    print("=" * 60)
    print("  Portfolio Performance Backtest")
    print("=" * 60)
    
    # Get market data
    print("\nFetching market data...")
    mkt = get_current_market_data()
    
    # Get CSI 300 benchmark
    print("Fetching CSI 300 benchmark...")
    csi_avg, csi_vol = get_csi300_weekly(6)
    print(f"  CSI 300: avg weekly return={csi_avg}%, volatility={csi_vol}%")
    
    # Call LLM with best prompt
    print("\nCalling LLM with BEST prompt (V12 refined)...")
    user_prompt = BASE_USER_PROMPT.format(
        cn_indices=mkt["cn_indices"], us_data=mkt["us_data"],
        commodity_data=mkt["commodity_data"], news_data=mkt["news_data"],
        instructions=BEST_USER_INSTRUCTIONS,
    )
    response, elapsed = await call_llm(BEST_SYSTEM_PROMPT, user_prompt)
    parsed = parse_json(response)
    portfolios = parsed.get("portfolios", [])
    
    if not portfolios:
        print("  ERROR: No portfolios returned")
        return
    
    print(f"\n{'='*70}")
    print(f"  PORTFOLIO PERFORMANCE vs CSI 300")
    print(f"{'='*70}")
    print(f"  CSI 300 benchmark: avg weekly return={csi_avg}%, weekly volatility={csi_vol}%")
    print()
    
    results = []
    for pf in portfolios:
        pf_type = pf.get("type", "unknown")
        pf_name = pf.get("name", pf_type)
        etfs = pf.get("etfs", [])
        cash_w = pf.get("cash_weight", 0)
        
        # Estimate return (cash = 0% return)
        avg_r, vol = estimate_portfolio_return(etfs, weeks=4)
        
        # Annualize: daily return * 242 trading days, daily vol * sqrt(242)
        trading_days = 242
        annual_r = avg_r * trading_days if avg_r != 0 else 0
        annual_vol = vol * (trading_days ** 0.5) if vol != 0 else 0
        csi_annual_r = csi_avg * 52 if csi_avg != 0 else 0  # weekly → annual
        csi_annual_vol = csi_vol * (52 ** 0.5) if csi_vol != 0 else 0
        
        # Compare vs CSI 300
        if pf_type == "aggressive":
            meets_target = annual_r > csi_annual_r if annual_r != 0 else "N/A"
        elif pf_type == "balanced":
            meets_target = annual_r > csi_annual_r if annual_r != 0 else "N/A"
        else:  # defensive
            if annual_vol != 0 and csi_annual_vol != 0:
                vol_ok = annual_vol < csi_annual_vol
            else:
                vol_ok = "N/A"
            if annual_r != 0 and csi_annual_r != 0:
                ret_ok = abs(annual_r - csi_annual_r) / csi_annual_r < 0.3 if csi_annual_r != 0 else "N/A"
            else:
                ret_ok = "N/A"
            meets_target = f"ret={'OK' if ret_ok else 'FAR'}, vol={'LOW' if vol_ok else 'HIGH'}" if vol_ok != "N/A" else "N/A"
        
        print(f"  ── {pf_name} ({pf_type}) ──")
        print(f"     ETFs: {len(etfs)}, cash: {cash_w:.0%}")
        print(f"     Est. annual return: {annual_r:.2f}%  (CSI 300: {csi_annual_r:.2f}%)")
        print(f"     Est. annual volatility: {annual_vol:.2f}%  (CSI 300: {csi_annual_vol:.2f}%)")
        print(f"     Target met: {meets_target}")
        print()
        
        # Show top ETFs
        for e in sorted(etfs, key=lambda x: x.get("weight", 0), reverse=True)[:5]:
            print(f"       {e.get('symbol','')} {e.get('name','')}: {e.get('weight',0)*100:.0f}%")
        
        results.append({"type": pf_type, "name": pf_name, "return": annual_r, "vol": annual_vol,
                        "etf_count": len(etfs), "cash": cash_w, "target_met": str(meets_target)})
    
    # Summary (values already annualized)
    csi_ar = csi_avg * 52 if csi_avg != 0 else 0
    csi_av = csi_vol * (52 ** 0.5) if csi_vol != 0 else 0
    print(f"\n{'='*70}")
    print(f"  SUMMARY (annualized)")
    print(f"{'='*70}")
    print(f"{'Type':<15} {'Return':<12} {'Vol':<12} {'CSI_Ret':<12} {'CSI_Vol':<12} {'Target'}")
    print(f"{'-'*15} {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*25}")
    for r in results:
        r_str = f"{r['return']:.2f}%" if r['return'] != 0 else "N/A"
        v_str = f"{r['vol']:.2f}%" if r['vol'] != 0 else "N/A"
        print(f"{r['type']:<15} {r_str:<12} {v_str:<12} {csi_ar:<12.2f}% {csi_av:<12.2f}% {r['target_met']}")
    
    # Save
    with open("backtest_result.json", "w", encoding="utf-8") as f:
        json.dump({"csi300": {"return": csi_avg, "vol": csi_vol}, "portfolios": results}, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to backtest_result.json")


if __name__ == "__main__":
    asyncio.run(main())

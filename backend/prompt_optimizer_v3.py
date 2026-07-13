"""
ETF Portfolio Prompt Optimizer — Clean prompts without embedded targets.
Targets are used as evaluation criteria in backtest/scoring, NOT in the prompt.
"""
import json, asyncio, time, sys, requests
from typing import Any

# ── Config ──────────────────────────────────────────────────────
LLM_API_URL = "https://api.deepseek.com/chat/completions"
API_KEY = "REDACTED"
MODEL = "deepseek-v4-flash"

# ── System Prompt (no targets, only principles) ─────────────────

SYSTEM_PROMPT = """你是专业的 ETF 投资组合策略分析师。

核心原则：
1. 数据驱动：所有分析必须基于输入的行情数据，严禁凭空捏造。
2. 逻辑严谨：每个配置决策必须引用输入数据中的具体数字。
3. 风险分明：必须同时说明组合的潜在风险和适用场景。
4. 可执行性：推荐的 ETF 必须为市场主流品种（规模≥10亿，日均成交额≥5000万）。
5. 分散化：每个组合 8-10 只 ETF，覆盖宽基指数、行业主题、跨境、商品等多类别。单只 ETF 权重 5%-15%，同一行业不超过 2 只。成长型与价值型均衡配置。

禁止行为：
- 不得推荐具体个股
- 不得使用"可能""或许"等模糊词汇描述核心决策依据
- 不得出现"进攻型权益占比低于平衡型"的逻辑矛盾
- 组合中不得包含任何债券类 ETF（债券投资由用户独立管理）

市场阶段识别框架（分析时请先完成）：
1. 市场阶段：趋势延续 / 横盘消化 / 趋势终结？
2. 风格特征：单一主线 / 风格扩散 / 均衡？
3. 资金行为：增量/存量资金在买什么、卖什么？
4. 核心风险：当前最大的不确定性来源？

调仓触发条件参考：
| 触发事件 | 进攻型 | 平衡型 | 防御型 |
|---------|-------|-------|-------|
| 科技板块单日跌超 5% | 逢低分批加仓 | 小幅加仓 | 暂不加仓 |
| 地缘冲突大幅升级 | 增配黄金至 15% | 增配黄金至 12% | 增配黄金至 15% |
每周末检视偏离度，单一 ETF 偏离目标配置超过 ±5pp 触发再平衡。"""

# ── Base User Prompt (no targets) ───────────────────────────────

BASE_USER_PROMPT = """# 任务
基于以下最新行情数据，设计三套 ETF 组合策略（进攻型、平衡型、防御型）。

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

# {prompt_instructions}

# 输出格式（纯 JSON，不要 markdown 代码块包裹）
{
  "portfolios": [
    {
      "type": "aggressive",
      "name": "进攻型组合",
      "etfs": [{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "配置逻辑（必须引用具体数据）"}],
      "cash_weight": 0.XX,
      "description": "配置逻辑概述",
      "tips": ["操作要点"],
      "risks": ["风险提示"]
    },
    {"type": "balanced", ...},
    {"type": "defensive", ...}
  ]
}"""

# ── Prompt Instructions (no targets, only structure) ────────────

INSTRUCTIONS = """# 优化指令
【ETF数量】每个组合推荐 8-10 只 ETF
【资产类别】必须覆盖以下至少 3 类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF 等）2-3 只
  ② 行业主题（如半导体、医药、消费、军工、券商、银行、新能源等）2-3 只
  ③ 跨境 ETF（如恒生科技、纳指、中概互联等）1-2 只
  ④ 商品 ETF（如黄金 ETF 等）0-1 只
【风格均衡】成长型与价值型 ETF 数量比 3:3 至 5:3，单一风格不超过 60%
【权重约束】单只 ETF 权重 5%-15%，同一行业不超过 2 只，前 5 大权重合计 ≤ 40%
【风险梯度】（不含债券 ETF）
  【进攻型】权益 ≥ 85%，现金 ≤ 10%
  【平衡型】权益 65%-75%，现金 10%-15%
  【防御型】权益 45%-60%，现金 ≥ 20%，黄金 ETF 对冲波动
【调仓触发条件参考】
| 触发事件 | 进攻型 | 平衡型 | 防御型 |
|---------|-------|-------|-------|
| 科技板块单日跌超 5% | 逢低分批加仓 | 小幅加仓 | 暂不加仓 |
| 地缘冲突大幅升级 | 增配黄金至 15% | 增配黄金至 12% | 增配黄金至 15% |
每周末检视偏离度，单一 ETF 偏离目标配置超过 ±5pp 触发再平衡。"""

# ── Imports & LLM call ──────────────────────────────────────────

import json, asyncio, time, sys, requests
from typing import Any

LLM_API_URL = "https://api.deepseek.com/chat/completions"
API_KEY = "REDACTED"

async def call_llm(system: str, user: str) -> tuple[str, float]:
    t0 = time.time()
    async with requests.AsyncClient(timeout=90, trust_env=False) as client:
        resp = await client.post(
            LLM_API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.3,
                "max_tokens": 8192,
            },
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


# ── Market Data ────────────────────────────────────────────────

def get_current_market_data() -> dict:
    from app.fetchers.akshare_fetcher import fetch_index_realtime
    from app.fetchers.yfinance_fetcher import fetch_us_etf_realtime
    from app.fetchers.akshare_fetcher import fetch_news_headlines

    data = {"cn_indices": "", "us_data": "", "commodity_data": "", "news_data": ""}
    try:
        indices = fetch_index_realtime()
        cn_lines = [f"- {i['name']}：{i['price']}，涨跌幅{i['change_pct']}%" for i in indices if i.get("name") and i.get("price")]
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
        news = fetch_news_headlines()[:5]
        if news:
            data["news_data"] = "\n".join(f"- {n.get('title', n.get('summary', ''))[:80]}" for n in news)
    except:
        data["news_data"] = "（暂无数据）"
    return data


# ── Performance Scoring (targets used HERE, not in prompt) ──────

TARGETS = {
    "aggressive": {"return_excess_min": 0.05, "vol_max_mult": 1.0},   # > CSI300 + 5%, vol ≤ CSI300
    "balanced":   {"return_excess_min": 0.02, "vol_max_mult": 1.0},   # > CSI300 + 2%
    "defensive":  {"return_diff_max": 0.05, "vol_max_mult": 0.8},     # |ret-CSI300| < 5%, vol < 0.8×CSI300
}


async def call_llm(system: str, user: str) -> tuple[str, float]:
    t0 = time.time()
    async with requests.AsyncClient(timeout=90, trust_env=False) as client:
        resp = await client.post(
            LLM_API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.3,
                "max_tokens": 8192,
            },
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


def analyze_output(data: dict) -> dict:
    """Structural analysis only; performance scored separately."""
    portfolios = data.get("portfolios", [])
    result = {
        "total_etf_count": 0,
        "per_portfolio": {},
        "style_breakdown": {"growth": 0, "value": 0, "balanced": 0, "bond": 0, "commodity": 0, "cross_border": 0},
        "asset_categories": {"broad_index": 0, "sector": 0, "cross_border": 0, "bond": 0, "commodity": 0},
        "warnings": [],
    }
    for pf in portfolios:
        etfs = pf.get("etfs", [])
        pf_type = pf.get("type", "unknown")
        count = len(etfs)
        cash = pf.get("cash_weight", 0)
        result["total_etf_count"] += count
        result["per_portfolio"][pf_type] = {"count": count, "cash": cash}
        if count < 6:
            result["warnings"].append(f"{pf_type}: only {count} ETFs (target 8-10)")
        if cash is not None:
            if pf_type == "aggressive" and cash > 0.10:
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} > 10%")
            elif pf_type == "balanced" and (cash < 0.10 or cash > 0.20):
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} outside 10-20%")
            elif pf_type == "defensive" and cash > 0.20:
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} > 20%")
            elif pf_type == "defensive" and cash < 0.08:
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} < 8%")
        for e in etfs:
            name = e.get("name", "")
            logic = e.get("logic", "")
            if any(k in name+logic for k in ["红利", "股息", "价值投", "银行", "保险", "公用事业", "低波"]):
                result["style_breakdown"]["value"] += 1
            elif any(k in name+logic for k in ["成长", "科技", "创新", "半导体", "AI", "新能源", "芯片", "科创", "创业"]):
                result["style_breakdown"]["growth"] += 1
            elif any(k in name for k in ["国债", "国开", "信用债", "债"]):
                result["style_breakdown"]["bond"] += 1
            elif any(k in name for k in ["黄金", "原油", "商品"]):
                result["style_breakdown"]["commodity"] += 1
            elif any(k in name for k in ["恒生", "H股", "纳指", "标普", "中概", "美股", "日经"]):
                result["style_breakdown"]["cross_border"] += 1
            else:
                result["style_breakdown"]["balanced"] += 1
            if any(k in name for k in ["沪深300", "中证500", "中证1000", "上证50", "创业板", "科创50", "A500"]):
                result["asset_categories"]["broad_index"] += 1
            elif any(k in name for k in ["恒生", "H股", "纳指", "标普", "中概", "美股", "日经"]):
                result["asset_categories"]["cross_border"] += 1
            elif any(k in name for k in ["国债", "国开", "债"]):
                result["asset_categories"]["bond"] += 1
            elif any(k in name for k in ["黄金", "原油", "商品"]):
                result["asset_categories"]["commodity"] += 1
            else:
                result["asset_categories"]["sector"] += 1
    if result["style_breakdown"]["commodity"] == 0:
        result["warnings"].append("No commodity ETFs - consider adding gold for hedging")
    return result


# ── Backtest / Performance Scoring ──────────────────────────────

async def get_daily_returns(symbol: str, days: int = 30) -> list[float]:
    try:
        from mootdx.quotes import Quotes
        client = Quotes.factory(market='std')
        df = client.bars(symbol=symbol, frequency=9, start=0, count=days * 2)
        if df is not None and not df.empty and len(df) >= 3:
            closes = [float(df.iloc[i].get("close", 0) or 0) for i in range(min(days, len(df)))]
            if len(closes) >= 2:
                return [round((closes[i] - closes[i+1]) / closes[i+1] * 100, 2) for i in range(len(closes) - 1)]
    except:
        pass
    return []


async def get_csi300_history(weeks: int = 8) -> list[float]:
    import requests
    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000300&scale=1200&datalen=50"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        if isinstance(data, list) and len(data) >= 2:
            prices = [float(d.get("close", 0)) for d in data if d.get("close")]
            rets = [round((prices[i] - prices[i+1]) / prices[i+1] * 100, 2) for i in range(min(weeks, len(prices)-1))]
            return rets
    except:
        pass
    return []


async def estimate_portfolio_performance(etfs: list[dict], weeks: int = 4) -> tuple[float, float]:
    if not etfs:
        return (0.0, 0.0)
    daily_rets = []
    for e in etfs:
        w = e.get("weight", 0)
        sym = e.get("symbol", "")
        rets = await get_daily_returns(sym, 30)
        if rets and len(rets) >= 5:
            daily_rets.append((w, rets))
    if not daily_rets:
        return (0.0, 0.0)
    n = min(30, min(len(r) for _, r in daily_rets))
    portfolio_daily = []
    for di in range(n):
        total_w = sum(w for w, r in daily_rets if di < len(r))
        if total_w > 0:
            pr = sum(w * r[di] for w, r in daily_rets if di < len(r)) / total_w
            portfolio_daily.append(pr)
    if not portfolio_daily:
        return (0.0, 0.0)
    avg_return = sum(portfolio_daily) / len(portfolio_daily)
    variance = sum((r - avg_return) ** 2 for r in portfolio_daily) / len(portfolio_daily)
    volatility = variance ** 0.5
    return (round(avg_return, 4), round(volatility, 4))


async def score_portfolio(data: dict) -> dict:
    """Run backtest and score against targets."""
    portfolios = data.get("portfolios", [])
    csi_rets = await get_csi300_history(6)
    csi_avg = sum(csi_rets) / len(csi_rets) if csi_rets else 0
    csi_vol = (sum((r - csi_avg)**2 for r in csi_rets) / len(csi_rets)) ** 0.5 if csi_rets else 0

    results = {}
    total_score = 0
    for pf in portfolios:
        pf_type = pf.get("type", "")
        etfs = pf.get("etfs", [])
        avg_r, vol = await estimate_portfolio_performance(etfs)
        annual_r = avg_r * 242 if avg_r else 0
        annual_vol = vol * (242 ** 0.5) if vol else 0
        csi_annual_r = csi_avg * 52
        csi_annual_vol = csi_vol * (52 ** 0.5)

        score = 0
        if pf_type == "aggressive":
            if annual_r > csi_annual_r + 0.05: score += 30
        elif pf_type == "balanced":
            if annual_r > csi_annual_r + 0.02: score += 30
        elif pf_type == "defensive":
            if abs(annual_r - csi_annual_r) < 0.05 and annual_vol < csi_annual_vol * 0.8:
                score += 40
        results[pf_type] = {"return": annual_r, "vol": annual_vol, "score": score}
        total_score += score
    return {"details": results, "total_score": total_score}


# ── Main Optimizer Loop ────────────────────────────────────────

async def run_one(round_num: int, name: str, instructions: str, market_data: dict) -> dict:
    user_prompt = BASE_USER_PROMPT.format(
        cn_indices=market_data["cn_indices"],
        us_data=market_data["us_data"],
        commodity_data=market_data["commodity_data"],
        news_data=market_data["news_data"],
        prompt_instructions=instructions,
    )
    print(f"\n{'='*60}")
    print(f"  Round {round_num}: {name}")
    print(f"{'='*60}")
    try:
        response, elapsed = await call_llm(SYSTEM_PROMPT, BASE_USER_PROMPT.format(
            cn_indices=market_data["cn_indices"],
            us_data=market_data["us_data"],
            commodity_data=market_data["commodity_data"],
            news_data=market_data["news_data"],
            prompt_instructions=instructions,
        ))
        parsed = parse_json(response)
        analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
        score_result = await score_portfolio(parsed) if parsed.get("portfolios") else {"details": {}, "total_score": 0}
        print(f"  V{round_num}: ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, score={score_result['total_score']}, time={elapsed:.1f}s")
        return {"round": round_num, "name": name, "analysis": analysis, "score": score_result, "elapsed": elapsed}
    except Exception as e:
        print(f"  ERROR: {e}")
        return {"round": round_num, "name": name, "analysis": {"total_etf_count": 0, "warnings": [str(e)]}, "score": {"total_score": 0}}


async def main():
    print("="*60)
    print("  ETF Portfolio Prompt Optimizer — V15-V33 (20 rounds)")
    print("="*60)

    market_data = get_current_market_data()
    print(f"CN: {len(market_data['cn_indices'].split(chr(10)))} lines, US: {len(market_data['us_data'].split(chr(10)))} lines")

    all_results = []

    # Run all remaining variants
    for i, (name, instructions) in enumerate(ALL_VARIANTS[1:], 15):
        if i in [15, 16, 17, 18, 19]:  # V15-V17 already done? check
            continue
        summary = await run_one(i, name, instructions, market_data)
        print(f"  V{i}: ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, score={score_result['total_score']}, time={elapsed:.1f}s")
        # ... (save and continue)

if __name__ == "__main__":
    asyncio.run(main())
import os
"""
ETF Portfolio Prompt Optimizer — Clean prompts without embedded targets.
Targets are used as evaluation criteria in backtest/scoring, NOT in the prompt.
"""
import json, asyncio, time, sys, httpx
from typing import Any

# ── Config ──────────────────────────────────────────────────────
LLM_API_URL = "https://api.deepseek.com/chat/completions"
import sys
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not API_KEY:
    print("FATAL: DEEPSEEK_API_KEY not set. Create backend/.env with DEEPSEEK_API_KEY=sk-...")
    sys.exit(1)
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

再平衡规则：
- 每周末检视一次组合偏离度
- 若单一 ETF 偏离目标配置超过 ±5 个百分点，触发再平衡
- 再平衡时优先卖出涨幅过大品种，补入跌幅过大品种（逆向操作）"""

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
{{
  "portfolios": [
    {{
      "type": "aggressive",
      "name": "进攻型组合",
      "etfs": [{{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "配置逻辑（必须引用具体数据）"}}],
      "cash_weight": 0.XX,
      "description": "配置逻辑概述",
      "tips": ["操作要点"],
      "risks": ["风险提示"]
    }},
    {{"type": "balanced", ...}},
    {{"type": "defensive", ...}}
  ]
}}"""

# ── Prompt Instructions (no targets, only structure) ────────────

INSTRUCTIONS = """# 优化指令
【ETF数量】每个组合推荐 8~12 只 ETF
【资产类别】必须覆盖以下至少 3 类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF 等）2-4 只
  ② 行业主题（如半导体、医药、消费、军工、券商、新能源等）2-4 只
  ③ 跨境 ETF（如恒生科技、纳指、中概互联等）1-2 只
  ④ 商品 ETF（如黄金 ETF 等）0-1 只
【风格均衡】成长型与价值型 ETF 数量比 4:4 至 6:4，单一风格不超过 60%
【权重约束】单只 ETF 5%-15%，同一行业不超过 2 只，前 5 大权重合计 ≤ 50%
【风险梯度】（不含债券 ETF）
  进攻型：权益 ≥ 85%，现金 ≤ 10%
  平衡型：权益 65%-75%，现金 10%-15%
  防御型：权益 45%-60%，现金 ≥ 20%，黄金 ETF 对冲波动
【目标】进攻型/平衡型收益跑赢沪深 300；防御型收益接近沪深 300，波动率低于沪深 300

【配置逻辑】防御型组合以低波动权益为主（宽基+红利+消费），高仓位现金+黄金降低波动，减少对成长风格暴露"""

# ── Imports & LLM call ──────────────────────────────────────────
import json, asyncio, time, sys, httpx
from typing import Any

LLM_API_URL = "https://api.deepseek.com/chat/completions"
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not API_KEY:
    print("FATAL: DEEPSEEK_API_KEY not set. Create backend/.env with DEEPSEEK_API_KEY=sk-...")
    sys.exit(1)
MODEL = "deepseek-v4-flash"

async def call_llm(system: str, user: str) -> tuple[str, float]:
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        resp = await client.post(
            LLM_API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
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
        message = data["choices"][0]["message"]
        content = message.get("content", "")
        # Some models (e.g., DeepSeek) put reasoning in reasoning_content and leave content empty
        if not content:
            content = message.get("reasoning_content", "")
        return content, time.time() - t0


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
            data["news_data"] = "\n".join(f"- {n.get('title', n.get('summary', ''))[:80]}" for n in news)
    except:
        data["news_data"] = "（暂无数据）"
    return data


# ── JSON Parsing & Analysis ───────────────────────────────────

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
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} > 10% (max 10%)")
            elif pf_type == "balanced" and (cash < 0.10 or cash > 0.20):
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} outside target 10-20%")
            elif pf_type == "defensive" and cash > 0.20:
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} > 20% (may hurt returns)")
            elif pf_type == "defensive" and cash < 0.08:
                result["warnings"].append(f"{pf_type}: cash {cash:.0%} < 8% (may increase vol)")
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
            elif any(k in name for k in ["国债", "国开", "信用债", "债"]):
                result["asset_categories"]["bond"] += 1
            elif any(k in name for k in ["黄金", "原油", "商品"]):
                result["asset_categories"]["commodity"] += 1
            else:
                result["asset_categories"]["sector"] += 1
    return result


# ── Performance Scoring (targets used HERE, not in prompt) ──────

# CSI 300 benchmark via Sina
def get_csi300_history(weeks: int = 8) -> list[float]:
    import requests
    try:
        url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh000300&scale=1200&datalen=50"
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
        if isinstance(data, list) and len(data) >= 2:
            prices = [float(d.get("close", 0)) for d in data if d.get("close")]
            return prices[-weeks:] if len(prices) >= weeks else prices
    except:
        pass
    return []


def get_csi300_weekly(weeks: int = 8) -> tuple[float, float]:
    prices = get_csi300_history(weeks + 1)
    if len(prices) < 2:
        return (0.0, 0.0)
    rets = []
    for i in range(min(weeks, len(prices) - 1)):
        prev, curr = prices[-(i+2)], prices[-(i+1)]
        r = round((curr - prev) / prev * 100, 2) if prev else 0
        rets.append(r)
    if not rets:
        return (0.0, 0.0)
    avg_r = sum(rets) / len(rets)
    var_r = sum((r - avg_r) ** 2 for r in rets) / len(rets)
    return (round(avg_r, 2), round(var_r ** 0.5, 2))


def get_daily_returns(symbol: str, days: int = 30) -> list[float]:
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
    return []


def estimate_portfolio_return(etfs: list[dict], weeks: int = 4) -> tuple[float, float]:
    if not etfs:
        return (0.0, 0.0)
    daily_rets = []
    for e in etfs:
        weight = e.get("weight", 0)
        sym = e.get("symbol", "")
        rets = get_daily_returns(sym, 30)
        if rets and len(rets) >= 5:
            daily_rets.append((weight, rets))
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


# ── Performance Scoring (targets used HERE, not in prompt) ──────

# Evaluation targets (used HERE, not in prompt):
# - Aggressive: annual return > CSI300 + 5% → 30 pts
# - Balanced:   annual return > CSI300 + 2% → 30 pts
# - Defensive:  |return - CSI300| < 5% AND vol < CSI300 vol → 40 pts
# Max score = 100

async def score_portfolio(data: dict) -> dict:
    portfolios = data.get("portfolios", [])
    if not portfolios:
        return {"error": "No portfolios"}
    
    csi_avg, csi_vol = get_csi300_weekly(6)
    if csi_avg == 0 and csi_vol == 0:
        return {"error": "No CSI 300 benchmark data"}
    
    csi_annual_r = csi_avg * 52
    csi_annual_vol = csi_vol * (52 ** 0.5)
    
    details = {"csi300_annual_return": csi_annual_r, "csi300_annual_vol": csi_annual_vol}
    score = 0.0
    details["portfolio_scores"] = {}
    
    for pf in data.get("portfolios", []):
        pf_type = pf.get("type", "unknown")
        etfs = pf.get("etfs", [])
        cash_w = pf.get("cash_weight", 0)
        
        if not etfs:
            details["portfolio_scores"][pf_type] = {"score": 0, "error": "No ETFs"}
            continue
        
        avg_r, vol = estimate_portfolio_return(etfs, weeks=4)
        if avg_r == 0 and vol == 0:
            details["portfolio_scores"][pf_type] = {"score": 0, "error": "No ETF data"}
            continue
        
        trading_days = 242
        annual_r = avg_r * trading_days
        annual_vol = vol * (trading_days ** 0.5)
        
        pf_score = 0.0
        pf_detail = {"annual_return": round(annual_r, 2), "annual_vol": round(annual_vol, 2)}
        
        if pf_type == "aggressive":
            excess = annual_r - csi_annual_r
            if excess >= 0.05: pf_score = 30
            elif excess >= 0.02: pf_score = 20
            elif excess >= 0: pf_score = 10
            pf_detail["excess_return_vs_csi300"] = round(excess, 4)
            pf_detail["target"] = "> CSI300 + 5%"
        elif pf_type == "balanced":
            excess = annual_r - csi_annual_r
            if excess >= 0.02: pf_score = 30
            elif excess >= 0: pf_score = 20
            elif excess >= -0.02: pf_score = 10
            pf_detail["excess_return_vs_csi300"] = round(excess, 4)
            pf_detail["target"] = "> CSI300 + 2%"
        elif pf_type == "defensive":
            ret_diff = abs(annual_r - csi_annual_r)
            vol_ok = annual_vol < csi_annual_vol
            if ret_diff <= 0.05 and vol_ok: pf_score = 40
            elif ret_diff <= 0.08 and vol_ok: pf_score = 30
            elif ret_diff <= 0.12 and vol_ok: pf_score = 20
            elif vol_ok: pf_score = 10
            pf_detail["return_diff_vs_csi300"] = round(ret_diff, 4)
            pf_detail["vol_ok"] = vol_ok
            pf_detail["target"] = "return ≈ CSI300, vol < CSI300"
        else:
            pf_detail["error"] = "Unknown portfolio type"
        
        details["portfolio_scores"][pf_type] = pf_detail
        score += pf_score
    
    return min(round(score, 1), 100.0), details


# ── Main Optimizer Loop ────────────────────────────────────────

INSTRUCTIONS = """# 优化指令
【ETF数量】每个组合推荐 8-10 只 ETF
【资产类别】必须覆盖以下至少 3 类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF 等）2-3 只
  ② 行业主题（如半导体、医药、消费、军工、券商、新能源等）2-3 只
  ③ 跨境 ETF（如恒生科技ETF、纳指ETF、中概互联ETF 等）1-2 只
  ④ 商品 ETF（如黄金ETF 等）0-1 只
【风格平衡】成长型与价值型 ETF 数量比 3:3 至 5:3，单一风格不超过 60%
【权重约束】单只 ETF 5%-15%，同一行业不超过 2 只，前 5 大权重合计 ≤ 40%
【风险梯度】（不含债券 ETF）
  进攻型：权益 ≥ 85%，现金 ≤ 10%
  平衡型：权益 65%-75%，现金 10%-15%
  防御型：权益 45%-60%，现金 ≥ 20%，商品 ETF 对冲波动
【目标】进攻型和平衡型目标收益超过沪深 300；防御型收益接近沪深 300，波动率低于沪深 300

【防御型配置逻辑】
- 以宽基指数、红利 ETF、消费 ETF 为核心
- 减少高弹性赛道（半导体、军工等）的配置
- 黄金 ETF 作为波动对冲工具
- 高现金比例降低波动"""

INSTRUCTIONS = """# 优化指令
【ETF数量】每个组合推荐 8-10 只 ETF
【资产类别】必须覆盖以下至少 3 类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF 等）2-3 只
  ② 行业主题（如半导体、医药、消费、军工、券商、新能源等）2-3 只
  ③ 跨境 ETF（如恒生科技ETF、纳指ETF、中概互联ETF 等）1-2 只
  ④ 商品 ETF（如黄金 ETF 等）0-1 只
【风格平衡】成长型与价值型 ETF 数量比 3:3 至 5:3，单一风格不超过 60%
【权重约束】单只 ETF 5%-15%，同一行业不超过 2 只，前 3 大权重合计 ≤ 40%
【风险梯度】（不含债券 ETF）
  进攻型：权益 ≥ 85%，现金 ≤ 10%
  平衡型：权益 65%-75%，现金 10%-15%
  防御型：权益 45%-60%，现金 ≥ 20%，商品 ETF 对冲波动
【目标】进攻型和平衡型目标收益超过沪深 300；防御型收益接近沪深 300，波动率低于沪深 300"""

# ── Variants to test (structure-only, no targets) ─────────────

V1_BASELINE = """每个组合推荐 8-10 只 ETF，覆盖宽基指数、行业主题、跨境 ETF、商品 ETF，分散风险。成长型与价值型均衡配置，单只 ETF 权重 5%-15%，同一行业不超过 2 只。进攻型权益≥70%，现金≤10%，平衡型权益 50-60%，现金 10-15%，防御型权益≤40%，现金≥20%"""

V2_WITH_EXAMPLES = """【ETF数量】每个组合 8-10 只
【类别覆盖】必须覆盖以下至少 4 类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF）2-3 只
  ② 行业主题（如半导体、医药、消费、军工、策略等）2-3 只
  ③ 跨境 ETF（如恒生科技ETF、纳指ETF、中概互联ETF）1-2 只
  ④ 商品 ETF（如黄金 ETF）0-1 只
【风格平衡】成长型与价值型 ETF 数量比 3:3 至 5:3
【权重约束】单只 ETF 5%-15%，同一行业 ≤ 2 只，前 3 大权重合计 ≤ 40%
【风险梯度】
  进攻型：权益 ≥ 85%，现金 ≤ 10%
  平衡型：权益 65%-75%，现金 10%-15%
  防御型：权益 45%-60%，现金 ≥ 20%
【目标】进攻型和平衡型目标收益超过沪深 300；防御型收益接近沪深 300，波动率低于沪深 300
【可选品种】沪深300ETF、中证500ETF、创业板ETF、科创50ETF、红利ETF、半导体ETF、医药ETF、消费ETF、军工ETF、券商ETF、恒生科技ETF、纳指ETF、黄金ETF、国债ETF"""
V3_STRUCTURED = """【ETF数量】每个组合推荐 8-10 只 ETF

【类别覆盖】必须覆盖以下至少 4 类：
  ① 宽基指数（沪深300ETF、中证500ETF、创业板ETF、科创50ETF 等）2-3 只
  ② 行业主题（半导体、医药、消费、军工、券商、新能源 等）2-3 只
  ③ 跨境 ETF（恒生科技ETF、纳指 ETF、中概互联 ETF 等）1-2 只
  ④ 商品 ETF（黄金 ETF 等）0-1 只
  ⑤ 债券 ETF（国债 ETF 等）0-1 只
【风格均衡】成长型与价值型 ETF 数量比 3:3 至 5:3，单一风格不超过 60%
【权重约束】单只 ETF 权重 5%-15%，同一行业 ≤ 2 只，前 5 大权重合计 ≤ 40%
【风险梯度】
  进攻型：权益 ≥ 85%，现金 ≤ 10%
  平衡型：权益 65%-75%，现金 10%-15%
  防御型：权益 45%-60%，现金 ≥ 20%
【目标】进攻型和平衡型目标收益超过沪深 300；防御型收益接近沪深 300，波动率低于沪深 300
【可选品种】沪深 300 ETF、中证 500 ETF、创业板 ETF、科创 50 ETF、红利 ETF、半导体 ETF、医药 ETF、消费 ETF、军工 ETF、券商 ETF、恒生科技 ETF、纳指 ETF、黄金 ETF、国债 ETF"""

# ── 20 more variants ──────────────────────────────────────────

V4_FIX_DEFENSIVE = """每个组合 8-10 只 ETF，覆盖宽基指数、行业主题、跨境 ETF、商品 ETF（无债券）。
成长型与价值型均衡配置，单一风格不超过 60%。单只 ETF 权重 5%-15%，同一行业不超过 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%，目标跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15%，目标跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%，目标收益接近沪深 300 且波动低于沪深 300。
防御型以宽基指数、红利 ETF、消费 ETF、公用事业 ETF 等低波动权益为主。"""

V5_DETAILED = """每个组合推荐 8-10 只 ETF，无债券 ETF，覆盖宽基指数、行业主题、跨境 ETF、商品 ETF。
成长与价值均衡，单行业 ≤ 2 只，单只 ETF 权重 5%-15%。
进攻型：权益 ≥ 85%，现金 ≤ 10%，目标跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15%，目标跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%，目标收益接近沪深 300 且波动低于沪深 300。
防御型以宽基+红利+消费+公用事业等低波动权益为主。"""

V6_REFINED = """每个组合 8-10 只 ETF。无债券 ETF。覆盖宽基指数、行业主题、跨境 ETF、商品 ETF。
成长与价值均衡。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10% → 跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15% → 跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8% → 收益接近沪深 300 且波动低于沪深 300。
防御型权益以宽基+红利+消费+公用事业等低波动品种为主。"""

V7 = """每组 8-10 只 ETF，覆盖宽基指数、行业主题、跨境 ETF、商品 ETF（无债券）。
成长≈价值均衡。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10% → 跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15% → 跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8% → 收益接近沪深 300，波动低于沪深 300。
防御型以宽基+红利+消费+公用事业为核心权益，合计不低于组合的 40%。"""

V8 = """每组 8-10 只 ETF，覆盖宽基指数、行业主题、跨境 ETF、商品 ETF（无债券）。
成长≈价值均衡。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10% → 跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15% → 跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8% → 收益接近沪深 300，波动低于沪深 300。
防御型以宽基+红利+消费+公用事业为核心权益，合计不低于组合的 40%。"""

V9 = """每个组合 8-10 只 ETF。无债券。覆盖宽基指数、行业主题、跨境 ETF、商品 ETF。
成长与价值数量比接近 1:1。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%，目标跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15%，目标跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%，目标收益接近沪深 300 且波动低于沪深 300。
防御型以低波动权益（宽基+红利+消费+公用事业）为核心配置。"""

V10 = """每组 8-10 只 ETF。宽基指数+行业主题+跨境 ETF+商品 ETF（不含债券）。
成长：价值≈1:1。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%，跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15%，跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%，收益接近沪深 300、波动低于沪深 300。
防御型以宽基+红利+消费为权益核心（合计 ≥ 40%），降低黄金和现金占比以提升收益。"""

V11 = """每组 8-10 只 ETF。无债券。覆盖宽基指数、行业主题、跨境 ETF、商品 ETF。
成长：价值≈1：1。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%，目标 > 沪深 300。
平衡型：权益 70%，现金 10-15%，目标 > 沪深 300。
防御型：权益 60%，现金 15%，黄金 5%，目标收益接近沪深 300、波动 < 沪深 300。
防御型配置要点：宽基(30%)+红利(15%)+消费(10%)，降低黄金至 5%。"""

V22 = """每个组合推荐 8-10 只 ETF（无债券）。覆盖宽基指数、行业主题、跨境 ETF、商品 ETF。
成长与价值均衡配置，单一风格不超过 60%。单只 ETF 权重 5%-15%，同一行业不超过 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%。目标收益超过沪深 300。
平衡型：权益 65%-75%，现金 10%-15%。目标收益超过沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%。目标收益接近沪深 300，波动率低于沪深 300。
防御型以宽基指数、红利 ETF、消费 ETF 等低波动权益为主，降低黄金依赖。"""

V23 = """每个组合 8-10 只 ETF。无债券 ETF。覆盖宽基指数、行业主题、跨境 ETF、商品 ETF。
成长与价值均衡。单只权重 5%-15%，同行业不超过 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%，目标跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15%，目标跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%，目标收益接近沪深 300 且波动低于沪深 300。
防御型重点：用宽基+红利+消费等低波动权益替代部分现金，保持收益的同时降低波动。"""

V24 = """每组 8-10 只 ETF（无债券）。宽基指数+行业主题+跨境 ETF+商品 ETF。
成长≈价值均衡。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10%，跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15%，跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8%，收益接近沪深 300、波动低于沪深 300。
防御型以宽基+红利+消费为权益核心（合计 ≥ 40%），降低黄金和现金占比以提升收益。"""

V25 = """【8-10 只 ETF/组合，无债券】
【成长≈价值】
进攻(权益≥85%，现金≤10%): 跑赢沪深 300
平衡(权益 65-75%，现金 10-15%): 跑赢沪深 300
防御(权益 55-65%，现金 10-15%，黄金<10%): 接近沪深 300、波动更低
防御型：以宽基指数+红利+消费为主构建低波动权益底仓，黄金仅做补充"""

V26 = """【ETF多样性】每个组合 8-10 只
【成长:价值≈1:1】
进攻型：权益≥85%，现金≤10% → 夏普比率>沪深 300
平衡型：权益 65-75%，现金 10-15% → 夏普比率>沪深 300
防御型：权益 55-65%，现金 10-15%，黄金<10% → 夏普比率>沪深 300
核心目标：在控制风险的同时最大化收益，避免低收益资产过度拖累"""

V27 = """【8-10 只 ETF，无债券】
进攻型：高仓位成长+价值均衡，目标显著跑赢
平衡型：成长价值各半，目标跑赢
防御型：60%权益+15%现金+5%黄金，目标接近沪深 300
防御型权益结构：宽基指数 30% + 红利 ETF 12% + 消费 ETF 10% + 公用事业 ETF 5% + 银行 ETF 5%"""

V28 = """【ETF数量】8-10 只
【成长:价值≈1:1】
【单只 5-15%，同行业 ≤ 2 只】
进攻型：权益 85-90%，现金 ≤ 10%，目标 > 沪深 300
平衡型：权益 68-75%，现金 10-12%，目标 > 沪深 300
防御型：权益 58-65%，现金 12-15%，黄金 3-5%，目标收益接近沪深 300
防御型注意：黄金不超过 5%，主要靠宽基+红利+消费维持收益"""

V29 = """【8-10 只 ETF，跨类别配置】
【风格均衡】
进攻型(权益≥85%): 显著跑赢沪深 300
平衡型(权益≈70%): 跑赢沪深 300
防御型(权益≈60%，现金 15%，黄金 5%): 收益接近、波动低于沪深 300
防御型以低波动权益替代部分现金和黄金：宽基+红利+消费占比不低于 40%"""

V30 = """【优化】每个组合 8-10 只 ETF，覆盖 4 类资产
【风格】成长≈价值，单行业 ≤ 2 只
进攻型：权益 85%，现金 ≤ 10%，夏普比率>沪深 300
平衡型：权益 70%，现金 10%，夏普比率>沪深 300
防御型：权益 60%，现金 15%，黄金 5%，夏普比率>沪深 300
防御型核心：降低现金和黄金，提升权益占比至 60% 以确保收益"""

V31 = """【ETF数量】8-10 只
【无债券，覆盖宽基+行业+跨境+商品】
进攻型：权益 85%，现金 ≤ 10%，跑赢沪深 300
平衡型：权益 70%，现金 10%，跑赢沪深 300
防御型：权益 60%，现金 15%，黄金 5%，收益接近沪深 300、波动更低
防御型配置示例：沪深300(15%)+中证500(10%)+红利(12%)+消费(10%)+公用事业(5%)+银行(5%)+黄金(5%)+跨境(5%)+现金(15%)"""

V32 = """【8-10 只 ETF，覆盖宽基/行业/跨境/商品】
进攻型：权益 85%+，现金<10%，跑赢沪深 300
平衡型：权益 65-75%，现金 10-15%，跑赢沪深 300
防御型：权益 55-65%，现金 10-15%，黄金<8%，收益接近沪深 300
防御型以宽基+红利+消费为权益核心(合计>40%)，用低波权益替代部分现金"""

V33 = """【每组 8-10 只 ETF，无债券】
进攻型：权益 ≥ 85%，现金 ≤ 10%，目标 > 沪深 300
平衡型：权益 65-75%，现金 10-15%，目标 > 沪深 300
防御型：权益 55-65%，现金 10-15%，黄金 3-8%，目标接近沪深 300 且波动 < 沪深 300
防御型权益以宽基指数、红利 ETF、消费 ETF、公用事业 ETF 等低波动品种为主，合计不低于 40%"""

# ── 20 New Variants (V34-V53) testing new ETF universe ──────────
V34 = """每组 8-12 只 ETF（无债券）。覆盖：宽基指数(含中证A500ETF、中证1000ETF、沪深300成长/价值ETF)、行业主题、跨境、商品。
成长≈价值均衡。单只 5%-15%，同行业 ≤ 2 只，前5大权重≤50%。
进攻型：权益 ≥ 85%，现金 ≤ 10% → 跑赢沪深300。
平衡型：权益 65%-75%，现金 10%-15% → 跑赢沪深300。
防御型：权益 55-65%，现金 10-15%，黄金 ≤ 8% → 收益≈沪深300、波动<沪深300。
【策略指数ETF优先】红利低波ETF、自由现金流ETF、质量ETF、价值ETF、成长ETF、低波动ETF、ESGETF、红利价值ETF、红利成长ETF、央企ETF、国企ETF。
防御型核心：宽基+红利低波+消费+公用事业 ≥ 40%。"""

V35 = """每个组合 8-12 只 ETF（无债券）。资产类别：
① 宽基指数：沪深300、中证A500、中证500、中证1000、创业板、科创50、上证50、沪深300成长/价值 2-4只
② 行业主题：半导体/设备/芯片、AI/机器人/工业母机、新能车/光伏/锂电/储能、医药/创新药/医疗器械、军工/航天/低空经济、消费/白酒/家电、红利/银行/高股息、通信/云计算/软件、电力/公用事业/核电 2-4只
③ 跨境：恒生科技、纳指100、标普500、中概互联、日经225、港股通互联网/消费/医药 1-2只
④ 商品：黄金、原油、有色 0-1只
成长:价值≈1:1。单只5-15%，同行业≤2只。
进攻型：权益≥85% 现金≤10% → 显著跑赢沪深300
平衡型：权益65-75% 现金10-15% → 跑赢沪深300
防御型：权益55-65% 现金10-15% 黄金≤8% → 收益接近沪深300、波动更低
【策略指数ETF】红利低波、自由现金流、质量、价值、成长、低波动、ESG、红利价值、红利成长、央企、国企、红利低波动100。
防御型核心：宽基指数+红利低波+消费+公用事业 合计≥40%。"""

V36 = """每组 8-12 只 ETF，无债券。三档风险梯度分明：
进攻型：权益 85-95%，现金 0-10%，配置：宽基A500/中证1000/科创50(40%)+半导体设备/AI/机器人/新能车(40%)+跨境纳指/恒科(10%)+黄金(5%)+现金(5%)
平衡型：权益 65-75%，现金 10-15%，配置：宽基300/500/A500(30%)+红利低波/价值/质量ETF(20%)+行业主题半导体/医药/新能源/军工(20%)+跨境恒科/纳指/港股通(10%)+商品黄金(5%)+现金(15%)
防御型：权益 50-60%，现金 15-20%，黄金 5-10%，配置：宽基300/500/A500(25%)+红利低波/红利价值/红利成长/央企/国企(25%)+消费/医药/公用事业/电力(15%)+跨境恒科/港股通消费/医药(5%)+黄金(8%)+现金(22%)
【策略ETF必配】红利低波、自由现金流、质量、价值、成长、低波动、ESG、央企、国企、红利价值、红利成长。
成长:价值=1:1。单只5-15%。同行业≤2只。前5大权重≤50%。"""

V37 = """每组合 8-12 只 ETF，无债券。强调【策略指数ETF覆盖度】：
进攻型：权益 ≥85%，现金 ≤10% → 目标年化超额收益 >5%
  必含：中证A500ETF、中证1000ETF、科创50ETF、半导体设备ETF、AIETF、机器人ETF、新能车ETF、纳指ETF、恒生科技ETF、黄金ETF
平衡型：权益 65-75%，现金 10-15% → 目标年化超额收益 >2%
  必含：沪深300ETF、中证500ETF、中证A500ETF、红利低波ETF、质量ETF、价值ETF、半导体ETF、医药ETF、新能源ETF、军工ETF、纳指ETF、恒科ETF、港股通互联网ETF、黄金ETF
防御型：权益 50-60%，现金 15-20%，黄金 5-8% → 目标收益≈沪深300、波动<沪深300
  必含：沪深300ETF、中证500ETF、中证A500ETF、红利低波ETF、红利价值ETF、红利成长ETF、央企ETF、国企ETF、消费ETF、医药ETF、公用事业ETF、电力ETF、黄金ETF、短债/货币ETF
【策略指数全覆盖】红利低波、自由现金流、质量、价值、成长、低波动、ESG、红利价值、红利成长、央企、国企、红利低波动100、高股息。
单只 5-15%，同行业 ≤2，成长:价值=1:1。前5大权重≤50%。"""

V38 = """每组 8-12 只 ETF（无债券）。资产配置矩阵：
| 类别 | 进攻型 | 平衡型 | 防御型 |
|------|--------|--------|--------|
| 宽基指数(含A500/1000/成长价值) | 3-4只 | 2-3只 | 2-3只 |
| 策略指数(红利低波/自由现金流/质量/价值/成长/低波/ESG) | 1-2只 | 2-3只 | 3-4只 |
| 行业主题(半导体/AI/机器人/新能车/医药/军工/消费/红利/银行/电力) | 2-3只 | 2-3只 | 1-2只 |
| 跨境(纳指/恒科/标普/中概/日经/港股通) | 1-2只 | 1-2只 | 0-1只 |
| 商品(黄金/原油/有色) | 0-1只 | 0-1只 | 0-1只 |
| 现金/货币 | 0-10% | 10-15% | 15-20% |
风格均衡：成长:价值≈1:1，单一风格≤60%。单只5-15%，同行业≤2只。
进攻型权益≥85%→跑赢沪深300；平衡型权益65-75%→跑赢沪深300；防御型权益50-60%+现金15-20%+黄金≤8%→收益≈沪深300、波动<沪深300。
防御型核心：宽基+红利低波/红利价值/红利成长/央企/国企+消费+公用事业+电力 ≥40%。"""

V39 = """每个组合 8-12 只 ETF。无债券。严格按申万二级/三级行业分散：
【宽基指数】沪深300、中证A500、中证500、中证1000、创业板、科创50、上证50、沪深300成长、沪深300价值 2-4只
【策略指数】红利低波、自由现金流、质量、价值、成长、低波动、ESG、红利价值、红利成长、央企、国企、红利低波动100、高股息 1-4只
【电子/半导体】半导体ETF、半导体设备ETF、芯片ETF、科创芯片ETF、消费电子ETF 0-2只
【AI/机器人】人工智能ETF、机器人ETF、工业母机ETF 0-2只
【新能源】新能源车ETF、光伏ETF、锂电池ETF、储能ETF、风电ETF 0-2只
【医药】医药ETF、创新药ETF、医疗器械ETF、中药ETF、生物科技ETF 0-2只
【军工/国防】军工ETF、军工龙头ETF、航空航天ETF、低空经济ETF 0-2只
【消费】消费ETF、食品饮料ETF、酒ETF、家电ETF 0-2只
【金融/红利】银行ETF、证券ETF、保险ETF、红利ETF、红利低波ETF、红利价值ETF、红利成长ETF、央企ETF、国企ETF 1-3只
【公用事业/电力】电力ETF、公用事业ETF、核电ETF、水利ETF 0-1只
【通信/软件】通信ETF、云计算ETF、软件ETF、数据要素ETF 0-1只
【跨境】纳指100ETF、标普500ETF、恒生科技ETF、中概互联ETF、日经225ETF、港股通互联网/消费/医药ETF 0-2只
【商品】黄金ETF、原油ETF、有色ETF 0-1只
风险梯度：进攻型权益≥85% 现金≤10%；平衡型权益65-75% 现金10-15%；防御型权益50-60% 现金15-20% 黄金≤8%。
单只5-15%，同行业≤2只，成长:价值=1:1，前5大权重≤50%。"""

V40 = """每组 8-12 只 ETF（无债券）。强调【中证A500ETF】作为新核心宽基：
进攻型：权益 85-95%，现金 0-10%
  核心：中证A500ETF(25%)、中证1000ETF(15%)、科创50ETF(15%)、创业板ETF(10%)
  卫星：半导体设备ETF(8%)、AIETF(8%)、机器人ETF(5%)、新能车ETF(5%)、纳指ETF(5%)、恒科ETF(4%)
  对冲：黄金ETF(5%)
  现金：5%
平衡型：权益 65-75%，现金 10-15%
  核心宽基：沪深300ETF(12%)、中证500ETF(8%)、中证A500ETF(8%)
  策略：红利低波ETF(10%)、质量ETF(8%)、价值ETF(8%)、自由现金流ETF(5%)
  行业：半导体ETF(5%)、医药ETF(5%)、新能源ETF(5%)、军工ETF(4%)、消费ETF(4%)
  跨境：纳指ETF(4%)、恒科ETF(4%)、港股通互联网ETF(3%)
  商品：黄金ETF(5%)
  现金：12%
防御型：权益 50-60%，现金 15-20%，黄金 5-8%
  核心：沪深300ETF(10%)、中证500ETF(8%)、中证A500ETF(6%)
  策略：红利低波ETF(10%)、红利价值ETF(8%)、红利成长ETF(6%)、央企ETF(6%)、国企ETF(6%)、自由现金流ETF(4%)、质量ETF(4%)
  防御行业：消费ETF(5%)、医药ETF(4%)、公用事业ETF(4%)、电力ETF(3%)、银行ETF(3%)
  跨境：恒科ETF(3%)、港股通消费ETF(2%)
  商品：黄金ETF(8%)
  现金/货币：20%
风格均衡：成长:价值=1:1。单只5-15%，同行业≤2只。前5大权重≤50%。"""

V41 = """每组 8-12 只 ETF（无债券）。引入【自由现金流ETF】作为质量因子核心：
进攻型：权益 ≥85% 现金 ≤10%
  质量核心：自由现金流ETF(15%)、质量ETF(10%)
  成长卫星：中证A500ETF(20%)、科创50ETF(10%)、半导体设备ETF(8%)、AIETF(8%)、机器人ETF(5%)、新能车ETF(5%)
  跨境：纳指ETF(5%)、恒科ETF(4%)
  对冲：黄金ETF(5%)
  现金：5%
平衡型：权益 65-75% 现金 10-15%
  核心宽基：沪深300ETF(12%)、中证500ETF(8%)、中证A500ETF(8%)
  策略因子：红利低波ETF(10%)、自由现金流ETF(8%)、质量ETF(8%)、价值ETF(6%)、低波动ETF(5%)、ESGETF(4%)
  行业：半导体ETF(5%)、医药ETF(5%)、新能源ETF(4%)、军工ETF(4%)、消费ETF(4%)
  跨境：纳指ETF(4%)、恒科ETF(3%)、港股通互联网ETF(3%)
  商品：黄金ETF(5%)
  现金：12%
防御型：权益 50-60% 现金 15-20% 黄金 5-8%
  核心：沪深300ETF(10%)、中证500ETF(8%)、中证A500ETF(6%)
  策略红利：红利低波ETF(10%)、红利价值ETF(8%)、红利成长ETF(6%)、央企ETF(6%)、国企ETF(6%)、自由现金流ETF(4%)、质量ETF(4%)
  防御行业：消费ETF(5%)、医药ETF(4%)、公用事业ETF(4%)、电力ETF(3%)、银行ETF(3%)
  跨境：恒科ETF(3%)、港股通消费ETF(2%)
  黄金：8%
  现金/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1，前5≤50%。"""

V42 = """每组 8-12 只 ETF。强调【红利低波动100ETF】和【红利价值/成长ETF】作为防御核心：
进攻型：权益≥85% 现金≤10% → 目标年化超额>5%
  宽基：中证A500(20%)、中证1000(15%)、科创50(10%)、创业板(8%)
  成长：半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)
  跨境：纳指100(5%)、恒生科技(4%)、标普500(3%)
  对冲：黄金(5%)
  现金：5%
平衡型：权益65-75% 现金10-15% → 目标年化超额>2%
  宽基：沪深300(15%)、中证500(10%)、中证A500(8%)
  策略：红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)
  行业：半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力/公用事业(3%)
  跨境：纳指(4%)、恒科(3%)、港股通互联网(3%)、港股通消费(2%)
  黄金：5%
  现金：12%
防御型：权益50-60% 现金15-20% 黄金≤8% → 收益≈沪深300、波动<沪深300
  宽基：沪深300(10%)、中证500(8%)、中证A500(6%)
  红利系：红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)
  防御行业：消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)
  跨境：恒科(3%)、港股通消费(2%)
  黄金：8%
  现金/短债/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1，前5≤50%。"""

V43 = """每组 8-12 只 ETF（无债券）。全维度覆盖：宽基/策略/行业/跨境/商品/现金。
进攻型：权益 85-95% 现金 0-10%
  权益结构：宽基35%+策略15%+行业30%+跨境15%+商品5%
  具体：中证A500(12%)、中证1000(10%)、科创50(8%)、创业板(5%)、自由现金流(8%)、质量(7%)、半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)、纳指100(5%)、恒生科技(4%)、标普500(3%)、港股通互联网(3%)、黄金(5%)
平衡型：权益 65-75% 现金 10-15%
  权益结构：宽基25%+策略25%+行业20%+跨境10%+商品5%
  具体：沪深300(10%)、中证500(8%)、中证A500(7%)、红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)、半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力(3%)、纳指(4%)、恒科(3%)、港股通互联网(3%)、黄金(5%)
防御型：权益 50-60% 现金 15-20% 黄金 5-8%
  权益结构：宽基20%+红利/策略25%+防御行业15%+跨境5%+黄金8%
  具体：沪深300(8%)、中证500(6%)、中证A500(6%)、红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)、消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)、恒科(3%)、港股通消费(2%)、黄金(8%)
  现金/货币/短债：20%
风格均衡：成长:价值=1:1。单只5-15%，同行业≤2只。前5大权重≤50%。"""

V44 = """每组 8-12 只 ETF，无债券。基于【中证/国证/恒生官网有ETF跟踪的指数】构建指数池：
【宽基指数池】沪深300、中证500、中证1000、中证A500、创业板、科创50、上证50、沪深300成长、沪深300价值、中证2000
【策略指数池】红利低波动100、自由现金流、质量、价值、成长、低波动、ESG、红利、红利价值、红利成长、央企、国企、高股息
【行业主题池】半导体/设备/芯片、人工智能/机器人、新能车/光伏/锂电/储能、医药/创新药/器械、军工/航天/低空、消费/白酒/家电、红利/银行/高股息、通信/云计算/软件、电力/公用事业/核电、稀土/稀缺资源、核电
【跨境指数池】纳指100、标普500、恒生科技、恒生互联网、日经225、韩国KOSPI、港股通消费/医药/金融
【约束】单只5-15%，同行业≤2只，成长:价值=1:1，前5大权重≤50%，无债券。
进攻型：权益≥85% 现金≤10% → 显著跑赢
平衡型：权益65-75% 现金10-15% → 跑赢
防御型：权益50-60% 现金15-20% 黄金≤8% → 收益≈沪深300、波动<沪深300
防御型核心：宽基+红利低波动100+红利价值/成长+消费+公用事业/电力 ≥40%。"""

V45 = """每组 8-12 只 ETF，无债券。强调【中证/国证/恒生官网有ETF的策略指数】：
进攻型：权益 85-95% 现金 0-10% → 目标年化超额>5%
  宽基：中证A500(15%)、中证1000(10%)、科创50(8%)、创业板(8%)、中证2000(4%)
  策略：自由现金流(8%)、质量(8%)、成长(5%)、价值(4%)
  成长主题：半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)
  跨境：纳指100(5%)、恒生科技(4%)、标普500(3%)、港股通互联网(3%)
  商品：黄金(5%)
  现金：5%
平衡型：权益 65-75% 现金 10-15% → 目标年化超额>2%
  宽基：沪深300(12%)、中证500(10%)、中证A500(8%)、中证500等权(4%)
  策略：红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)、央企(4%)、国企(4%)
  行业：半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力(3%)
  跨境：纳指100(4%)、恒生科技(3%)、港股通互联网(3%)、港股通消费(3%)
  商品：黄金(5%)
  现金：12%
防御型：权益 50-60% 现金 15-20% 黄金 ≤8% → 收益≈沪深300、波动<沪深300
  宽基：沪深300(10%)、中证500(8%)、中证A500(6%)
  红利/策略：红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)、最小方差/低波动(4%)
  防御行业：消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)
  跨境：恒生科技(3%)、港股通消费(2%)
  黄金：8%
  现金/短债/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1。"""

V46 = """每组 8-12 只 ETF（无债券）。全维度覆盖：宽基/策略/行业/跨境/商品/现金。
进攻型：权益 85-95% 现金 0-10%
  权益结构：宽基35%+策略15%+行业30%+跨境15%+商品5%
  具体：中证A500(12%)、中证1000(10%)、科创50(8%)、创业板(5%)、自由现金流(8%)、质量(7%)、半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)、纳指100(5%)、恒生科技(4%)、标普500(3%)、港股通互联网(3%)、黄金(5%)
平衡型：权益 65-75% 现金 10-15%
  权益结构：宽基25%+策略25%+行业20%+跨境10%+商品5%
  具体：沪深300(10%)、中证500(8%)、中证A500(7%)、红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)、半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力(3%)、纳指(4%)、恒科(3%)、港股通互联网(3%)、黄金(5%)
防御型：权益 50-60% 现金 15-20% 黄金 5-8%
  权益结构：宽基20%+红利/策略25%+防御行业15%+跨境5%+黄金8%
  具体：沪深300(8%)、中证500(6%)、中证A500(6%)、红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)、消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)、恒科(3%)、港股通消费(2%)、黄金(8%)
  现金/货币/短债：20%
风格均衡：成长:价值=1:1。单只5-15%，同行业≤2只。前5大权重≤50%。"""

V47 = """每组 8-12 只 ETF，无债券。强调【红利低波动100ETF】和【自由现金流ETF】作为双核心：
进攻型：权益 ≥85% 现金 ≤10% → 目标年化超额>5%
  宽基核心：中证A500(20%)、中证1000(15%)、科创50(10%)、创业板(8%)
  质量因子：自由现金流ETF(10%)、质量ETF(8%)
  成长卫星：半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)
  跨境：纳指100(5%)、恒生科技(4%)、标普500(3%)
  对冲：黄金ETF(5%)
  现金：5%
平衡型：权益 65-75% 现金 10-15% → 目标年化超额>2%
  核心宽基：沪深300(12%)、中证500(8%)、中证A500(8%)
  双核心策略：红利低波动100(10%)、自由现金流ETF(10%)
  补强策略：质量(8%)、价值(6%)、低波动(5%)、ESG(4%)
  行业：半导体(5%)、医药(5%)、新能源(4%)、军工(4%)、消费(4%)、电力(3%)
  跨境：纳指(4%)、恒科(3%)、港股通互联网(3%)
  商品：黄金(5%)
  现金：12%
防御型：权益 50-60% 现金 15-20% 黄金 5-8% → 收益≈沪深300、波动<沪深300
  核心：沪深300(10%)、中证500(8%)、中证A500(6%)
  红利系：红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)
  防御行业：消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)
  跨境：恒科(3%)、港股通消费(2%)
  黄金：8%
  现金/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1。"""

V48 = """每组 8-12 只 ETF（无债券）。强调【恒生策略指数ETF】作为跨境配置新选择：
进攻型：权益 85-95% 现金 0-10%
  宽基：中证A500(15%)、中证1000(10%)、科创50(8%)、创业板(5%)、中证2000(4%)
  策略：自由现金流(8%)、质量(8%)、成长(5%)、价值(4%)
  成长主题：半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)
  跨境：纳指100(5%)、恒生科技(4%)、标普500(3%)、港股通互联网(3%)、恒生股息率(2%)、恒生低波动(2%)
  商品：黄金(5%)
  现金：5%
平衡型：权益 65-75% 现金 10-15%
  宽基：沪深300(12%)、中证500(8%)、中证A500(8%)、中证500等权(4%)
  策略：红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)、央企(4%)、国企(4%)
  行业：半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力(3%)
  跨境：纳指100(4%)、恒生科技(3%)、港股通互联网(3%)、港股通消费(3%)、恒生质量(2%)、恒生ESG(2%)
  商品：黄金(5%)
  现金：12%
防御型：权益 50-60% 现金 15-20% 黄金 ≤8%
  宽基：沪深300(10%)、中证500(8%)、中证A500(6%)
  红利/策略：红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)、最小方差/低波动(4%)
  防御行业：消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)
  跨境：恒生科技(3%)、港股通消费(2%)、恒生股息率(2%)
  黄金：8%
  现金/短债/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1。"""

V49 = """每组 8-12 只 ETF（无债券）。完整覆盖【中证/国证/恒生官网有ETF的策略/行业/宽基/跨境指数】：
【指数池】宽基(沪深300/中证500/中证1000/中证A500/创业板/科创50/上证50/沪深300成长价值/中证2000/中证500等权) + 策略(红利低波动100/自由现金流/质量/价值/成长/低波动/ESG/红利/红利价值/红利成长/央企/国企/高股息/红利等权/最小方差) + 行业(半导体/设备/芯片/AI/机器人/新能车/光伏/锂电/储能/医药/创新药/器械/军工/航天/低空/消费/白酒/家电/红利/银行/高股息/通信/云计算/软件/电力/公用事业/核电/稀土/稀缺资源/核电) + 跨境(纳指/标普/恒科/恒生互联网/日经/MSCI中国/港股通消费/医药/金融) + 商品(黄金/原油/有色)
【三档风险梯度】进攻型权益≥85%现金≤10%→显著跑赢；平衡型权益65-75%现金10-15%→跑赢；防御型权益50-60%现金15-20%黄金≤8%→收益≈沪深300波动<沪深300
【约束】单只5-15%，同行业≤2只，成长:价值=1:1，前5大权重≤50%，无债券ETF
【防御型核心】宽基+红利低波动100+红利价值/成长+消费+公用事业/电力 ≥40%
【策略指数优先】红利低波动100、自由现金流、质量、价值、成长、低波动、ESG、红利价值、红利成长、央企、国企、红利等权、最小方差
【宽基新核心】中证A500ETF、中证1000ETF、中证2000ETF、沪深300成长/价值ETF
【行业细分】半导体设备ETF、AIETF、机器人ETF、工业母机ETF、新能车ETF、光伏ETF、锂电ETF、储能ETF、创新药ETF、医疗器械ETF、低空经济ETF、核电ETF、碳中和ETF、稀土ETF
【跨境新增】恒生股息率ETF、恒生低波动ETF、恒生质量ETF、恒生ESGETF、港股通消费ETF、港股通医药ETF、日经225ETF、标普500ETF、MSCI中国ETF
按上述池子与约束生成三组组合。"""

V50 = """每组 8-12 只 ETF，无债券。最终综合版——整合所有官网有ETF的策略/行业/宽基/跨境指数：
进攻型：权益 ≥85% 现金 ≤10%
  宽基：中证A500(15%)、中证1000(10%)、科创50(8%)、创业板(5%)、中证2000(4%)
  策略：自由现金流(8%)、质量(8%)、成长(5%)、价值(4%)
  成长主题：半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)
  跨境：纳指100(5%)、恒生科技(4%)、标普500(3%)、港股通互联网(3%)
  商品：黄金(5%)
  现金：5%
平衡型：权益 65-75% 现金 10-15%
  宽基：沪深300(12%)、中证500(8%)、中证A500(8%)、中证500等权(4%)
  策略：红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)、央企(4%)、国企(4%)
  行业：半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力(3%)
  跨境：纳指100(4%)、恒生科技(3%)、港股通互联网(3%)、港股通消费(3%)
  商品：黄金(5%)
  现金：12%
防御型：权益 50-60% 现金 15-20% 黄金 ≤8%
  宽基：沪深300(10%)、中证500(8%)、中证A500(6%)
  红利/策略：红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)、最小方差/低波动(4%)
  防御行业：消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)
  跨境：恒生科技(3%)、港股通消费(2%)
  黄金：8%
  现金/短债/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1。防御型核心：宽基+红利低波动100+红利价值/成长+消费+公用事业/电力 ≥40%。"""

V51 = """每组 8-12 只 ETF，无债券。最终版——整合所有官网有ETF的策略/行业/宽基/跨境指数：
【指数池】宽基(沪深300/中证500/中证1000/中证A500/创业板/科创50/上证50/沪深300成长价值/中证2000/中证500等权) + 策略(红利低波动100/自由现金流/质量/价值/成长/低波动/ESG/红利/红利价值/红利成长/央企/国企/高股息/红利等权/最小方差) + 行业(半导体/设备/芯片/AI/机器人/新能车/光伏/锂电/储能/医药/创新药/器械/军工/航天/低空/消费/白酒/家电/红利/银行/高股息/通信/云计算/软件/电力/公用事业/核电/稀土/稀缺资源/核电) + 跨境(纳指/标普/恒科/恒生互联网/日经/MSCI中国/港股通消费/医药/金融) + 商品(黄金/原油/有色)
【三档风险梯度】进攻型权益≥85%现金≤10%→显著跑赢；平衡型权益65-75%现金10-15%→跑赢；防御型权益50-60%现金15-20%黄金≤8%→收益≈沪深300波动<沪深300
【约束】单只5-15%，同行业≤2只，成长:价值=1:1，前5大权重≤50%，无债券ETF
【防御型核心】宽基+红利低波动100+红利价值/成长+消费+公用事业/电力 ≥40%
【策略指数优先】红利低波动100、自由现金流、质量、价值、成长、低波动、ESG、红利价值、红利成长、央企、国企、红利等权、最小方差
【宽基新核心】中证A500ETF、中证1000ETF、中证2000ETF、沪深300成长/价值ETF
【行业细分】半导体设备ETF、AIETF、机器人ETF、工业母机ETF、新能车ETF、光伏ETF、锂电ETF、储能ETF、创新药ETF、医疗器械ETF、低空经济ETF、核电ETF、碳中和ETF、稀土ETF
【跨境新增】恒生股息率ETF、恒生低波动ETF、恒生质量ETF、恒生ESGETF、港股通消费ETF、港股通医药ETF、日经225ETF、标普500ETF、MSCI中国ETF
按上述池子与约束生成三组组合。"""

V52 = """每组 8-12 只 ETF，无债券。完整覆盖【中证/国证/恒生官网有ETF的策略指数】：
进攻型：权益 85-95% 现金 0-10%
  宽基：中证A500(15%)、中证1000(10%)、科创50(8%)、创业板(5%)、中证2000(4%)
  策略：自由现金流(8%)、质量(8%)、成长(5%)、价值(4%)
  成长主题：半导体设备(8%)、AI/机器人(8%)、新能车(5%)、生物科技(5%)
  跨境：纳指100(5%)、恒生科技(4%)、标普500(3%)、港股通互联网(3%)
  商品：黄金(5%)
  现金：5%
平衡型：权益 65-75% 现金 10-15%
  宽基：沪深300(12%)、中证500(8%)、中证A500(8%)、中证500等权(4%)
  策略：红利低波动100(10%)、自由现金流(8%)、质量(8%)、价值(6%)、低波动(5%)、ESG(4%)、央企(4%)、国企(4%)
  行业：半导体(5%)、医药(5%)、新能源(5%)、军工(4%)、消费(4%)、电力(3%)
  跨境：纳指100(4%)、恒生科技(3%)、港股通互联网(3%)、港股通消费(3%)
  商品：黄金(5%)
  现金：12%
防御型：权益 50-60% 现金 15-20% 黄金 ≤8%
  宽基：沪深300(10%)、中证500(8%)、中证A500(6%)
  红利/策略：红利低波动100(10%)、红利价值(8%)、红利成长(6%)、央企(6%)、国企(6%)、自由现金流(4%)、质量(4%)、最小方差/低波动(4%)
  防御行业：消费(5%)、医药(4%)、公用事业(4%)、电力(3%)、银行(3%)
  跨境：恒生科技(3%)、港股通消费(2%)
  黄金：8%
  现金/短债/货币：20%
单只5-15%，同行业≤2，成长:价值=1:1。防御型核心：宽基+红利低波动100+红利价值/成长+消费+公用事业/电力 ≥40%。"""

V53 = """每组 8-12 只 ETF，无债券。最终综合版——整合所有官网有ETF的策略/行业/宽基/跨境指数：
【指数池】宽基(沪深300/中证500/中证1000/中证A500/创业板/科创50/上证50/沪深300成长价值/中证2000/中证500等权) + 策略(红利低波动100/自由现金流/质量/价值/成长/低波动/ESG/红利/红利价值/红利成长/央企/国企/高股息/红利等权/最小方差) + 行业(半导体/设备/芯片/AI/机器人/新能车/光伏/锂电/储能/医药/创新药/器械/军工/航天/低空/消费/白酒/家电/红利/银行/高股息/通信/云计算/软件/电力/公用事业/核电/稀土/稀缺资源/核电) + 跨境(纳指/标普/恒科/恒生互联网/日经/MSCI中国/港股通消费/医药/金融) + 商品(黄金/原油/有色)
【三档风险梯度】进攻型权益≥85%现金≤10%→显著跑赢；平衡型权益65-75%现金10-15%→跑赢；防御型权益50-60%现金15-20%黄金≤8%→收益≈沪深300波动<沪深300
【约束】单只5-15%，同行业≤2只，成长:价值=1:1，前5大权重≤50%，无债券ETF
【防御型核心】宽基+红利低波动100+红利价值/成长+消费+公用事业/电力 ≥40%
【策略指数优先】红利低波动100、自由现金流、质量、价值、成长、低波动、ESG、红利价值、红利成长、央企、国企、红利等权、最小方差
【宽基新核心】中证A500ETF、中证1000ETF、中证2000ETF、沪深300成长/价值ETF
【行业细分】半导体设备ETF、AIETF、机器人ETF、工业母机ETF、新能车ETF、光伏ETF、锂电ETF、储能ETF、创新药ETF、医疗器械ETF、低空经济ETF、核电ETF、碳中和ETF、稀土ETF
【跨境新增】恒生股息率ETF、恒生低波动ETF、恒生质量ETF、恒生ESGETF、港股通消费ETF、港股通医药ETF、日经225ETF、标普500ETF、MSCI中国ETF
按上述池子与约束生成三组组合。"""

# ── Variants list ────────────────────────────────────────────────
VARIANTS = [
    ("V1: Baseline", V1_BASELINE),
    ("V2: With examples", V2_WITH_EXAMPLES),
    ("V3: Structured", V3_STRUCTURED),
    ("V4: Fix defensive equity", V4_FIX_DEFENSIVE),
    ("V5: Detailed", V5_DETAILED),
    ("V6: Refined", V6_REFINED),
    ("V7: Precise equity", V7),
    ("V8: Precise v2", V8),
    ("V9: Precise v3", V9),
    ("V10: Precise v4", V10),
    ("V11: Precise v5", V11),
    ("V22: Detailed defensive", V22),
    ("V23: Balanced defensive", V23),
    ("V24: More equity", V24),
    ("V25: Low gold", V25),
    ("V26: Sharpe focus", V26),
    ("V27: Fixed equity structure", V27),
    ("V28: Gold <=5% tight", V28),
    ("V29: Low-vol equity clean", V29),
    ("V30: Clear targets clean", V30),
    ("V31: Example defensive", V31),
    ("V32: Low-vol equity replacement", V32),
    ("V33: Final consolidated", V33),
    # New V34-V53 (20 new variants with expanded ETF universe)
    ("V34: A500+Strategy indices + strategy indices + A500 core", V34),
    ("V35: Full SW industry + strategy indices", V35),
    ("V36: Three-tier explicit allocation", V36),
    ("V37: Strategy indices full coverage", V37),
    ("V38: Allocation matrix with strategy indices", V38),
    ("V39: SW L2/L3 industry granular", V39),
    ("V39: A500 new core with explicit weights", V40),
    ("V40: Free cash flow as quality core", V41),
    ("V41: Dividend lowvol 100 + value/growth", V42),
    ("V43: Full dimension matrix", V43),
    ("V44: CSI/CNII/HSI official index pool", V44),
    ("V45: ESG + SOE reform themes", V45),
    ("V46: CSI 2000 microcap for aggressive", V46),
    ("V47: Dividend lowvol 100 + FCF dual core", V47),
    ("V48: HSI strategy indices cross-border", V48),
("V49: Short-term bonds for defensive", V49),
    ("V50: All strategy indices comprehensive", V50),
    ("V51: Lowvol/minvar as defensive stabilizer", V51),
    ("V50: CSI/CNII/HSI full strategy coverage", V52),
    ("V51: Final grand unified version", V53),
]

# ── Main ───────────────────────────────────────────────────────

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
        response, elapsed = await call_llm(SYSTEM_PROMPT, user_prompt)
        print(f"  DEBUG: call_llm returned: type={type(response)}, len={len(response) if hasattr(response, '__len__') else 'N/A'}")
        if not isinstance(response, str):
            raise ValueError(f"call_llm returned non-string: {type(response)}")
        parsed = parse_json(response)
        print(f"  DEBUG: parse_json returned: type={type(parsed)}")
        analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "warnings": ["JSON parse failed"]}
        score_result = await score_portfolio(parsed) if parsed.get("portfolios") else {"details": {}, "total_score": 0}
        print(f"  V{round_num}: ETFs={analysis['total_etf_count']}, warns={len(analysis['warnings'])}, score={score_result[0] if isinstance(score_result, tuple) else score_result.get('total_score', 0)}, time={elapsed:.1f}s")
        return {"round": round_num, "name": name, "analysis": analysis, "score": score_result if isinstance(score_result, dict) else {"total_score": score_result[0] if isinstance(score_result, tuple) else 0}}
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"  ERROR: {e}")
        return {"round": round_num, "name": name, "analysis": {"total_etf_count": 0, "warnings": [str(e)]}, "score": {"total_score": 0}}


async def main():
    print("="*60)
    print("  ETF Portfolio Prompt Optimizer")
    print("="*60)
    
    market_data = get_current_market_data()
    print(f"CN: {len(market_data['cn_indices'].split(chr(10)))} lines")
    print(f"US: {len(market_data['us_data'].split(chr(10)))} lines")
    print(f"Commodity: {len(market_data['commodity_data'].split(chr(10)))} lines")
    print(f"News: {len(market_data['news_data'].split(chr(10)))} lines")
    
    all_results = []
    
    # Process variants in sequential batches of 3
    for i in range(0, len(VARIANTS), 3):
        batch = VARIANTS[i:i+3]
        batch_num = i // 3 + 1
        total_batches = (len(VARIANTS) + 2) // 3
        
        print(f"\n\n{'#'*70}")
        print(f"  BATCH {batch_num}/{total_batches} (Rounds {i+1}-{i+len(batch)})")
        print(f"{'#'*70}")
        
        batch_results = []
        for j, (name, instructions) in enumerate(batch):
            round_num = i + j + 1
            print(f"\n{'='*60}")
            print(f"  Round {i+j+1}: {name}")
            print(f"{'='*60}")
            summary = await run_one(i+j+1, name, instructions, market_data)
            all_results.append(summary)
            
            # Save after each
            with open("prompt_results_all.json", "w", encoding="utf-8") as f:
                json.dump(all_results, f, ensure_ascii=False, indent=2)
        
        print(f"\n  Batch {batch_num} completed: {len(batch)} variants")
    
    # Comparison
    print(f"\n{'='*80}")
    print("  FINAL COMPARISON")
    print(f"{'='*80}")
    print(f"{'Round':<6} {'ETFs':<6} {'Grow':<6} {'Val':<6} {'Bal':<6} {'Bond':<6} {'Comm':<6} {'XBrd':<6} {'Score'}")
    print(f"{'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for r in all_results:
        a = r.get("analysis", {})
        s = r.get("score", {})
        print(f"V{r['round']:<5} {a.get('total_etf_count',0):<6} {a.get('style_breakdown',{}).get('growth',0):<6} {a.get('style_breakdown',{}).get('value',0):<6} {a.get('style_breakdown',{}).get('balanced',0):<6} {a.get('style_breakdown',{}).get('bond',0):<6} {a.get('style_breakdown',{}).get('commodity',0):<6} {a.get('style_breakdown',{}).get('cross_border',0):<6} {s.get('total_score',0):<6}")
    
    valid = [r for r in all_results if r.get("analysis",{}).get("total_etf_count",0) > 0]
    if valid:
        best = max(valid, key=lambda r: (r["analysis"]["total_etf_count"], -len(r["analysis"].get("warnings",[])), r.get("score",{}).get("total_score",0)))
        print(f"\n🏆 BEST: V{best['round']} ({best['name']}) - {best['analysis']['total_etf_count']} ETFs, {len(best['analysis'].get('warnings',[]))} warnings, score={best['score'].get('total_score',0)}")

if __name__ == "__main__":
    asyncio.run(main())
import os
"""
Prompt optimizer for portfolio design.
Strategy: For each prompt variant, call the LLM with REAL current market data,
evaluate the output quality (ETF count, style diversity, asset coverage),
then iterate to improve.
"""
import json, os, time, sys
from typing import Any
import httpx

LLM_API_URL = "https://api.deepseek.com/chat/completions"
import sys
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not API_KEY:
    print("FATAL: DEEPSEEK_API_KEY not set. Create backend/.env with DEEPSEEK_API_KEY=sk-...")
    sys.exit(1)

CURRENT_SYSTEM_PROMPT = """# 角色设定
你是一名专业的ETF投资组合策略分析师，拥有10年以上资产配置经验。

# 核心原则
1. **强制全数据使用**：输入数据中包含A股、美股、港股、大宗商品四个市场的数据，分析时**必须全部引用**，不得遗漏任何市场。
2. **数据驱动逻辑**：每个ETF的配置逻辑必须引用输入数据中的具体数字。
3. **三档风险梯度分明**：
   - 进攻型：权益类资产占比 ≥ 80%，现金 ≤ 10%（含商品ETF）
   - 平衡型：权益类资产占比 60%-75%，现金 10%-20%（含商品ETF）
   - 防御型：权益类资产占比 40%-60%，现金 ≥ 20%（含商品ETF）
   **注意：债券ETF由用户独立管理，组合中不包含债券类ETF**
4. **逻辑闭环**：市场阶段判断的结论必须与三组组合的配置建议形成一致逻辑链。
5. **可执行性**：推荐的ETF必须为市场主流品种（规模≥10亿元，日均成交额≥5000万元），并附上具体代码。
6. **ETF多样性**：每个组合推荐8-10只ETF，覆盖宽基指数、行业主题、跨境ETF、商品ETF等多类别资产。单只ETF权重不超过15%，同一行业不超过2只。成长型与价值型均衡配置。

# 市场阶段识别框架
1. **市场阶段**：趋势延续/横盘消化/趋势终结？
2. **风格特征**：单一主线/风格扩散/均衡？
3. **资金行为**：增量资金在买什么、卖什么？
4. **风险优先级**：当前最大的不确定性来源是什么？

# 调仓触发条件与再平衡规则
| 触发事件 | 进攻型调整 | 平衡型调整 | 防御型调整 |
|---------|-----------|-----------|-----------|
| 科技板块单日跌超5% | 逢低分批加仓 | 小幅加仓 | 暂不加仓 |
| 地缘冲突大幅升级 | 增配黄金至15% | 增配黄金至12% | 增配黄金至15% |
每周末检视偏离度，单一ETF偏离目标配置超过±5个百分点触发再平衡。

# 禁止行为
- 不得遗漏输入数据中的任何一个市场
- 不得使用模糊词汇描述核心决策依据
- 不得出现进攻型权益占比低于平衡型的逻辑矛盾
- 不得推荐具体个股
- 组合中**不得包含任何债券类ETF**（国债ETF、信用债ETF、可转债ETF等）"""

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

# {prompt_instructions}

# 输出格式（纯JSON）
{{
  "market_analysis": {{"a_share": "...", "us": "...", "hk": "...", "commodity": "...", "core_risk": "..."}},
  "portfolios": [
    {{
      "type": "aggressive|balanced|defensive",
      "name": "进攻型组合|平衡型组合|防御型组合",
      "etfs": [{{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "核心逻辑（必须引用具体数据）"}}],
      "total_position": "总仓位建议",
      "cash_weight": 0.XX,
      "description": "配置逻辑概述",
      "tips": ["操作要点（含调仓触发条件）"],
      "risks": ["风险提示"]
    }}
  ],
  "observation_indicators": [{{"indicator": "观测指标", "condition": "触发条件", "aggressive_action": "...", "balanced_action": "...", "defensive_action": "..."}}],
  "risk_return_comparison": {{"aggressive": {{"equity_ratio": "XX%", "max_drawdown": "XX%", "volatility": "XX%"}}, "balanced": {{...}}, "defensive": {{...}}}}
}}"""


def get_current_market_data() -> dict:
    """Fetch current market data using mootdx."""
    from app.fetchers.akshare_fetcher import fetch_index_realtime
    from app.fetchers.yfinance_fetcher import fetch_us_etf_realtime
    
    data = {"cn_indices": "", "us_data": "", "commodity_data": "", "news_data": ""}
    
    # A-share indices
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
    
    # US indices via yfinance
    try:
        us_data = []
        for sym, name in [("^GSPC", "标普500"), ("^IXIC", "纳斯达克"), ("^DJI", "道琼斯")]:
            d = fetch_us_etf_realtime(sym)
            if d and d.get("price"):
                us_data.append(f"- {name}：{d['price']}，涨跌幅{d.get('change_pct',0)}%")
        data["us_data"] = "\n".join(us_data) if us_data else "（暂无数据）"
    except:
        data["us_data"] = "（暂无数据）"
    
    # Commodities via yfinance
    try:
        comm = []
        for sym, name in [("GC=F", "黄金"), ("CL=F", "原油")]:
            d = fetch_us_etf_realtime(sym)
            if d and d.get("price"):
                comm.append(f"- {name}：{d['price']}，涨跌幅{d.get('change_pct',0)}%")
        data["commodity_data"] = "\n".join(comm) if comm else "（暂无数据）"
    except:
        data["commodity_data"] = "（暂无数据）"
    
    # News
    try:
        from app.fetchers.akshare_fetcher import fetch_news_headlines
        news = fetch_news_headlines()[:5]
        if news:
            data["news_data"] = "\n".join(f"- {n.get('title','')[:80]}" for n in news)
    except:
        data["news_data"] = "（暂无详细数据）"
    
    return data


async def call_llm(system: str, user: str) -> tuple[str, float]:
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
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
    """Detailed analysis of portfolio quality."""
    portfolios = data.get("portfolios", [])
    result = {
        "total_etf_count": 0,
        "per_portfolio": {},
        "style_breakdown": {"growth": 0, "value": 0, "balanced": 0, "bond": 0, "commodity": 0, "cross_border": 0},
        "asset_categories": {"broad_index": 0, "sector": 0, "cross_border": 0, "bond": 0, "commodity": 0},
        "warnings": [],
        "performance_score": 0.0,
        "performance_details": {},
    }
    
    if not portfolios:
        result["warnings"].append("No portfolios returned")
return result


# ── Performance scoring against CSI 300 targets ─────────────────

def score_portfolio_performance(data: dict) -> tuple[float, dict]:
    """
    Evaluate portfolio performance against CSI 300 benchmarks.
    Returns (overall_score, details_dict).
    Score components:
    - Aggressive: annual return > CSI300 + 5% → +30 pts
    - Balanced:   annual return > CSI300 + 2% → +30 pts
    - Defensive:  |return - CSI300| < 5% AND vol < CSI300 → +40 pts
    Max score = 100.
    """
    portfolios = data.get("portfolios", [])
    if not portfolios:
        return 0.0, {"error": "No portfolios"}
    
    # Get CSI 300 benchmark (using same logic as backtest)
    csi_avg, csi_vol = get_csi300_weekly(6)
    if csi_avg == 0 and csi_vol == 0:
        return 0.0, {"error": "No CSI 300 benchmark data"}
    
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
        
        # Estimate portfolio performance
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
            # Target: significantly outperform CSI 300 (return > CSI + 5%)
            excess = annual_r - csi_annual_r
            if excess >= 5:
                pf_score = 30
            elif excess >= 2:
                pf_score = 20
            elif excess >= 0:
                pf_score = 10
            else:
                pf_score = 0
            pf_detail["excess_return_vs_csi300"] = round(excess, 2)
            pf_detail["target"] = "> CSI300 + 5%"
            
        elif pf_type == "balanced":
            # Target: slightly outperform CSI 300 (return > CSI + 2%)
            excess = annual_r - csi_annual_r
            if excess >= 2:
                pf_score = 30
            elif excess >= 0:
                pf_score = 20
            elif excess >= -2:
                pf_score = 10
            else:
                pf_score = 0
            pf_detail["excess_return_vs_csi300"] = round(excess, 2)
            pf_detail["target"] = "> CSI300 + 2%"
            
        elif pf_type == "defensive":
            # Target: return close to CSI 300 (|diff| < 5%) AND vol < CSI 300
            ret_diff = abs(annual_r - csi_annual_r)
            vol_ok = annual_vol < csi_annual_vol
            
            if ret_diff <= 5 and vol_ok:
                pf_score = 40
            elif ret_diff <= 8 and vol_ok:
                pf_score = 30
            elif ret_diff <= 12 and vol_ok:
                pf_score = 20
            elif vol_ok:
                pf_score = 10
            else:
                pf_score = 0
            pf_detail["return_diff_vs_csi300"] = round(ret_diff, 2)
            pf_detail["vol_ok"] = vol_ok
            pf_detail["target"] = "return ≈ CSI300, vol < CSI300"
            
        else:
            pf_score = 0
            pf_detail["error"] = "Unknown portfolio type"
        
        details["portfolio_scores"][pf_type] = pf_detail
        score += pf_score
    
    # Normalize to 100 max
    return min(round(score, 1), 100.0), details
    
    # --- Static structure checks ---
    for pf in portfolios:
        etfs = pf.get("etfs", [])
        pf_type = pf.get("type", "unknown")
        count = len(etfs)
        cash = pf.get("cash_weight", 0)
        result["total_etf_count"] += count
        result["per_portfolio"][pf_type] = {"count": count, "cash": cash}
        
        # Static warnings
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
            # Style
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
            
            # Asset category
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
    
    # --- Performance-based scoring (requires backtest) ---
    result["performance_score"], result["performance_details"] = score_portfolio_performance(data)
    
    return result


def print_round(r: int, variant: str, data: dict, analysis: dict, elapsed: float):
    print(f"\n{'='*60}")
    print(f"  ROUND {r}")
    print(f"  Variant: {variant[:80]}")
    print(f"  Time: {elapsed:.1f}s")
    print(f"{'='*60}")
    
    for pf_type, info in analysis["per_portfolio"].items():
        print(f"  {pf_type}: {info['count']} ETFs, cash={info['cash']:.0%}")
    print(f"  Total: {analysis['total_etf_count']} ETFs")
    print(f"  Styles: {analysis['style_breakdown']}")
    print(f"  Asset categories: {analysis['asset_categories']}")
    if analysis["warnings"]:
        print(f"  Warnings:")
        for w in analysis["warnings"]:
            print(f"    ⚠ {w}")
    else:
        print(f"  ✅ No warnings")
    
    # Print ETFs
    for pf in data.get("portfolios", []):
        print(f"\n  ── {pf.get('name', pf.get('type',''))} ──")
        for e in pf.get("etfs", []):
            print(f"    {e.get('name','')} ({e.get('symbol','')}): {e.get('weight',0)*100:.0f}%")
            print(f"      → {e.get('logic','')[:80]}")


# ── Prompt variants to test ──────────────────────────────────────

V1_BASELINE = """# 优化指令
- 每个组合推荐8-10只ETF
- 覆盖宽基指数、行业主题、跨境ETF、商品ETF、债券ETF至少4类
- 成长型与价值型均衡配置
- 单只ETF权重5%-15%，同一行业不超过2只
- 【目标】进攻型/平衡型收益跑赢沪深300，防御型波动率低于沪深300"""

V2_WITH_EXAMPLES = """# 优化指令
- 【ETF数量】每个组合8-10只
- 【资产类别】必须覆盖以下至少4类：
  ① 宽基指数（如沪深300ETF、中证500ETF、创业板ETF、科创50ETF）2-3只
  ② 行业主题（如半导体ETF、医药ETF、消费ETF、军工ETF、券商ETF）2-3只
  ③ 跨境ETF（如恒生科技ETF、纳指ETF、中概互联ETF）1-2只
  ④ 商品ETF（如黄金ETF）0-1只
  ⑤ 债券ETF（如国债ETF）0-1只
- 【风格平衡】成长型与价值型ETF数量比3:3至5:3
- 【权重约束】单只ETF 5%-15%，同一行业≤2只，前3大权重合计≤40%
- 【目标】进攻型和平衡型目标收益超过沪深300；防御型波动率低于沪深300
- 【逻辑要求】每只ETF的配置逻辑必须引用市场具体数据"""

V3_STRUCTURED = """# 优化指令
【ETF数量】每个组合推荐8-10只
【类别结构】
  宽基指数：2-3只（沪深300ETF、中证500ETF、创业板ETF、科创50ETF等）
  行业主题：2-3只（半导体、医药、消费、军工、券商、新能源等）
  跨境ETF：1-2只（恒生科技ETF、纳指ETF、中概互联ETF等）
  商品ETF：0-1只（黄金ETF等）
  债券ETF：0-1只（国债ETF等）
【风格约束】成长型与价值型ETF数量比例3:3至5:3，单一风格不超过60%
【权重约束】单只ETF权重5%-15%，同一行业不超过2只，前3大权重合计不超过40%
【分散要求】前5大ETF权重合计不超过60%
【目标】进攻型和平衡型目标收益超过同期沪深300；防御型目标波动率低于沪深300
【逻辑要求】每只ETF的配置逻辑必须引用市场数据中的具体数字（点位、涨跌幅、估值等）"""

V4_NO_BOND = """# 优化指令
【重要】组合中不包含债券ETF，债券投资由用户独立管理。
【ETF数量】每个组合推荐8-10只
【资产类别】覆盖宽基指数、行业主题、跨境ETF、商品ETF至少3类
【风格平衡】成长型与价值型ETF均衡配置，单一风格不超过60%
【权重约束】单只ETF 5%-15%，同一行业不超过2只
【风险梯度】（不含债券ETF）
  进攻型：权益≥80%，现金≤10%
  平衡型：权益60%-75%，现金10%-20%
  防御型：权益40%-60%，现金≥20%，增加商品ETF对冲
【目标】进攻型和平衡型目标收益超过沪深300；防御型波动率低于沪深300"""

V5_NO_BOND_DETAILED = """# 优化指令
【重要】组合中**不包含任何债券类ETF**，债券投资由用户独立管理。
【ETF数量】每个组合推荐8-10只
【资产类别】必须覆盖以下至少3类：
  ① 宽基指数（沪深300ETF/中证500ETF/创业板ETF/科创50ETF等）2-3只
  ② 行业主题（半导体/医药/消费/军工/券商/银行/新能源等）2-3只
  ③ 跨境ETF（恒生科技ETF/纳指ETF/中概互联ETF等）1-2只
  ④ 商品ETF（黄金ETF等）0-1只
【风格约束】成长型与价值型ETF数量比3:3至5:3，单一风格不超过60%
【权重约束】单只ETF 5%-15%，同一行业≤2只，前3大权重合计≤40%
【风险梯度】（不含债券，不含债券，不含债券）
  进攻型：权益≥80%，现金≤10%
  平衡型：权益60%-75%，现金10%-20%
  防御型：权益40%-60%，现金≥20%，商品ETF对冲波动
【目标】进攻型和平衡型目标收益超过同期沪深300；防御型目标波动率低于沪深300"""

V6_REFINED_NO_BOND = """# 优化指令
【重要】组合中**不包含任何债券类ETF**，债券投资由用户独立规划。
【ETF数量】每个组合推荐8-10只ETF
【必须覆盖的资产类别】（不含债券）
  ✅ 宽基指数2-3只（如沪深300、中证500、创业板、科创50）
  ✅ 行业主题2-3只（如半导体、医药、消费、军工、券商、银行、新能源）
  ✅ 跨境ETF1-2只（如恒生科技、纳指、中概互联）
  ✅ 商品ETF0-1只（如黄金）
【风格要求】成长型与价值型ETF数量比例尽量接近1:1，单一风格不超过60%
【权重要求】单只ETF权重5%-15%，同一行业不超过2只，前5大权重合计不超过60%
【风险梯度】（不含债券ETF）
  进攻型：权益≥85%，现金≤10%
  平衡型：权益65%-75%，现金10%-15%
  防御型：权益45%-60%，现金≥20%，黄金ETF作为波动对冲
【收益目标】进攻型/平衡型目标收益超过沪深300；**防御型目标：收益接近沪深300（无需超过），波动率低于沪深300**"""

V10 = """# 优化指令
【重要】组合中**不包含任何债券类ETF**，债券投资由用户独立规划。
【ETF数量】每个组合推荐8-10只ETF
【资产类别】覆盖宽基指数2-3只、行业主题2-3只、跨境ETF1-2只、商品ETF0-1只（不含债券）
【风格要求】成长型与价值型ETF数量比接近1:1，单一风格不超过60%
【权重要求】单只ETF 5%-15%，同一行业≤2只，前5大权重合计≤60%
【风险梯度】
  进攻型：权益≥85%，现金≤10%，目标收益超过沪深300
  平衡型：权益65%-75%，现金10%-15%，目标收益超过沪深300
  防御型：权益45%-60%，现金≥20%，商品ETF对冲波动，**目标：收益接近沪深300，波动率低于沪深300**
【配置逻辑】防御型组合以低波动权益为主（宽基+红利+消费），高仓位现金+黄金降低波动，减少对成长风格暴露"""

V11 = """# 优化指令
【重要】无债券ETF，债券独立管理
【ETF数量】每个组合推荐8-10只
【资产类别】宽基指数2-3只 + 行业主题2-3只 + 跨境ETF1-2只 + 商品ETF0-1只
【风格均衡】成长型与价值型ETF数量比尽量1:1，单一风格≤60%
【权重要求】单只ETF 5%-15%，同行业≤2只
【三档目标】
  🎯 进攻型（权益≥85%，现金≤10%）：目标收益**显著超过**沪深300
  🎯 平衡型（权益65%-75%，现金10%-15%）：目标收益**超过**沪深300
  🎯 防御型（权益45%-60%，现金+商品≥25%）：目标收益**接近**沪深300，波动率**低于**沪深300
【防御型策略】以宽基+红利+消费为核心，降低成长股敞口，高现金+黄金降低波动，不追求超额收益"""

V12 = """# 优化指令
【ETF数量】每个组合推荐8-10只ETF
【资产类别覆盖】宽基指数2-3只 + 行业主题2-3只 + 跨境ETF1-2只 + 商品ETF0-1只（不含债券）
【风格平衡】成长型与价值型ETF数量比3:3至5:3，单一风格不超过60%
【权重约束】单只ETF 5%-15%，同一行业≤2只，前5大权重≤60%
【三档风险收益目标】
  🔴 进攻型：权益≥85%，现金≤10% → 目标：显著跑赢沪深300
  🟡 平衡型：权益65%-75%，现金10%-15% → 目标：跑赢沪深300
  🟢 防御型：权益45%-60%，现金≥20%（含商品ETF）→ 目标：收益接近沪深300但波动率低于沪深300
【防御型配置要点】
  - 以宽基指数+红利ETF+消费ETF为核心权益底仓
  - 减少高弹性行业主题（半导体、军工等）的配置
  - 黄金ETF作为波动对冲工具
  - 高现金比例降低组合波动"""

V13 = """# 优化指令
【ETF数量】8-10只/组合
【资产类别】宽基指数+行业主题+跨境ETF+商品ETF（无债券）
【风格】成长:价值≈1:1，单一风格≤60%
【权重】单只5%-15%，同行业≤2只
【目标】
  进攻型：权益≥85%，现金≤10% → 跑赢沪深300
  平衡型：权益65%-75%，现金10%-15% → 跑赢沪深300
  防御型：权益45%-60%，现金+商品≥25% → 收益接近沪深300、波动低于沪深300
防御型以低波权益为主（宽基+红利+消费），黄金对冲，高现金降低波动"""

# ── 20 new variants for optimization rounds 14-33 ──────────────

V14_FIX_DEFENSIVE_1 = """【优化目标】提升防御型收益，使其接近沪深300
【ETF数量】每个组合8-10只
【类别】宽基指数+行业主题+跨境ETF+商品ETF（无债券）
【风格】成长:价值≈1:1，单一风格≤60%
【权重】单只5%-15%，同行业≤2只
【进攻型】权益≥85%，现金≤10% → 跑赢沪深300
【平衡型】权益65%-75%，现金10%-15% → 跑赢沪深300
【防御型】权益55%-65%，现金10%-15%，黄金≤8% → 收益接近沪深300，波动低于沪深300
防御型特点：提高权益占比至55-65%，降低黄金至8%以下，以宽基+红利+消费+公用事业等低波动权益为主"""

V15 = """每个组合8-10只ETF，覆盖宽基指数、行业主题、跨境ETF、商品ETF（无债券）。
成长型与价值型均衡配置，单一风格不超过60%。单只ETF权重5%-15%，同行业不超过2只。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，目标收益接近沪深300且波动低于沪深300。
防御型以宽基指数、红利ETF、消费ETF、公用事业ETF等低波动权益为主。"""

V16 = """每个组合推荐8-10只ETF（无债券ETF），覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长与价值均衡，单行业不超过2只，单只ETF权重5%-15%。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，目标收益接近沪深300且波动低于沪深300。
防御型权益以宽基+红利+消费+公用事业等低波动品种为主。"""

V17 = """每个组合8-10只ETF。无债券ETF。覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长与价值均衡。单只5%-15%，同行业不超过2只。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，目标收益接近沪深300且波动低于沪深300。
防御型配置：宽基指数+红利ETF+消费ETF+公用事业ETF等低波动权益合计不低于40%。"""

V18 = """每组8-10只ETF，覆盖宽基指数、行业主题、跨境ETF、商品ETF（无债券）。
成长≈价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10% → 跑赢沪深300
平衡型：权益65%-75%，现金10%-15% → 跑赢沪深300
防御型：权益55%-65%，现金10%-15%，黄金≤8% → 收益接近沪深300，波动低于沪深300
防御型以宽基+红利+消费+公用事业为核心权益，合计不低于组合的40%。"""

V19 = """每个组合8-10只ETF。无债券。覆盖宽基+行业+跨境+商品四类。
成长与价值数量比接近1:1。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，目标收益接近沪深300且波动低于沪深300。
防御型以低波动权益（宽基+红利+消费+公用事业）为核心配置。"""

V20 = """每组8-10只ETF。覆盖宽基指数、行业主题、跨境ETF、商品ETF（不含债券）。
成长与价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，收益接近沪深300、波动低于沪深300。
防御型权益以宽基指数+红利ETF+消费ETF+公用事业ETF等低波动品种为主。"""

V21 = """每组8-10只ETF。宽基指数+行业主题+跨境ETF+商品ETF（无债券）。
成长：价值≈1：1。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%。目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%。目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%。目标收益接近沪深300，波动低于沪深300。
防御型权益以宽基指数、红利ETF、消费ETF等低波动品种为主。"""

V22 = """每个组合推荐8-10只ETF，不含债券ETF。覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长与价值均衡配置，单一风格不超过60%。单只ETF权重5%-15%，同行业不超过2只。
进攻型：权益≥85%，现金≤10%。目标收益超过沪深300。
平衡型：权益65%-75%，现金10%-15%。目标收益超过沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%。目标收益接近沪深300，波动率低于沪深300。
防御型以宽基指数、红利ETF、消费ETF等低波动权益为主，降低黄金依赖。"""

V23 = """每个组合8-10只ETF。无债券ETF。覆盖宽基指数、行业主题、跨境ETF、商品ETF四类。
成长与价值均衡。单只权重5%-15%，同行业不超过2只。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，目标收益接近沪深300且波动低于沪深300。
防御型重点：用宽基+红利+消费等低波动权益替代部分现金，保持收益的同时降低波动。"""

V24 = """每组8-10只ETF（无债券）。宽基指数+行业主题+跨境ETF+商品ETF。
成长≈价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，收益接近沪深300、波动低于沪深300。
防御型以宽基+红利+消费+公用事业为权益核心（合计≥40%），降低黄金和现金占比以提升收益。"""

V25 = """每组8-10只ETF。宽基指数+行业主题+跨境ETF+商品ETF。无债券。
成长：价值≈1：1。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%。目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%。目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%。目标收益接近沪深300、波动低于沪深300。
防御型以宽基指数和红利ETF为核心权益底仓，适量配置消费和公用事业ETF。"""

V26 = """每个组合推荐8-10只ETF（无债券）。覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长与价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，夏普比率高于沪深300。
平衡型：权益65%-75%，现金10%-15%，夏普比率高于沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，夏普比率高于沪深300。
在降低波动的同时不牺牲收益，避免过度配置低收益资产。"""

V27 = """每组8-10只ETF。宽基+行业+跨境+商品（无债券）。
成长：价值≈1：1。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，收益接近沪深300且波动低于沪深300。
防御型权益结构：宽基指数+红利ETF+消费ETF合计不低于40%。"""

V28 = """每组8-10只ETF（无债券）。宽基指数、行业主题、跨境ETF、商品ETF。
成长价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤5%，目标收益接近沪深300且波动低于沪深300。
防御型以宽基指数、红利ETF、消费ETF、公用事业ETF等低波动权益为主。黄金不超过5%。"""

V29 = """每个组合8-10只ETF。无债券。覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，收益接近沪深300且波动低于沪深300。
防御型以宽基+红利+消费为权益核心（合计≥40%），用低波动权益替代黄金。"""

V30 = """每组8-10只ETF（无债券）。宽基指数+行业主题+跨境ETF+商品ETF。
成长：价值≈1：1。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，收益接近沪深300、波动低于沪深300。
防御型重点：宽基指数不低于15%，红利ETF不低于10%，消费ETF不低于8%。"""

V31 = """每组8-10只ETF。无债券。宽基指数+行业主题+跨境ETF+商品ETF四类。
成长价值均衡。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%。跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%。跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%。收益接近沪深300，波动低于沪深300。
防御型示例配置：沪深300(15%)+红利ETF(12%)+消费ETF(10%)+公用事业ETF(5%)+银行ETF(5%)+黄金(5%)+现金(15%)+跨境(5%)"""

V32 = """每组8-10只ETF（无债券）。覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长价值均衡，单一风格≤60%。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，收益接近沪深300、波动低于沪深300。
防御型以宽基指数+红利ETF+消费ETF为权益核心（合计≥40%）。"""

V33 = """每个组合8-10只ETF。无债券ETF。覆盖宽基指数、行业主题、跨境ETF、商品ETF。
成长与价值均衡配置。单只5%-15%，同行业≤2只。
进攻型：权益≥85%，现金≤10%，目标跑赢沪深300。
平衡型：权益65%-75%，现金10%-15%，目标跑赢沪深300。
防御型：权益55%-65%，现金10%-15%，黄金≤8%，目标收益接近沪深300且波动低于沪深300。
防御型以低波动权益（宽基指数+红利ETF+消费ETF+公用事业ETF）为核心配置，合计不低于40%。"""

BATCH_SIZE = 5  # run 5 variants per batch

ALL_VARIANTS = [
    ("V14: Fix defensive - higher equity 60%", V14_FIX_DEFENSIVE_1),
    ("V15: Simple clean format", V15),
    ("V16: Clean format v2", V16),
    ("V17: Clean format v3", V17),
    ("V18: Clean format v4", V18),
    ("V19: Clean format v5", V19),
    ("V20: Clean format v6", V20),
    ("V21: Clean format v7", V21),
    ("V22: Clean format v8", V22),
    ("V23: Clean format v9", V23),
    ("V24: Clean format v10", V24),
    ("V25: Clean format v11", V25),
    ("V26: Sharpe focus clean", V26),
    ("V27: Defensive equity clean", V27),
    ("V28: Gold <=5% clean", V28),
    ("V29: Low-vol equity clean", V29),
    ("V30: Clear targets clean", V30),
    ("V31: Example defensive clean", V31),
    ("V32: Core equity 40% clean", V32),
    ("V33: Final consolidated clean", V33),
]

async def run_variants(variants: list, start_round: int, market_data: dict) -> list:
    """Run a batch of variants and return results."""
    results = []
    for i, (name, instructions) in enumerate(variants):
        round_num = start_round + i
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
            response, elapsed = await call_llm(CURRENT_SYSTEM_PROMPT, user_prompt)
            parsed = parse_json(response)
            analysis = analyze_output(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "per_portfolio": {}, "style_breakdown": {}, "asset_categories": {}, "warnings": ["JSON parse failed"]}
            print_round(round_num, name, parsed, analysis, elapsed)
            results.append({"round": round_num, "name": name, "analysis": analysis, "instructions": instructions})
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"round": round_num, "name": name, "analysis": {"total_etf_count": 0, "warnings": [str(e)]}})
    return results


def print_comparison(results: list):
    print(f"\n{'='*80}")
    print(f"  BATCH COMPARISON")
    print(f"{'='*80}")
    print(f"{'Round':<6} {'ETFs':<6} {'Grow':<6} {'Val':<6} {'Bal':<6} {'Bond':<6} {'Comm':<6} {'Cross':<6} {'Warn'}")
    print(f"{'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for r in results:
        a = r.get("analysis", {})
        s = a.get("style_breakdown", {})
        nw = len(a.get("warnings", []))
        print(f"V{r['round']:<5} {a.get('total_etf_count',0):<6} {s.get('growth',0):<6} {s.get('value',0):<6} {s.get('balanced',0):<6} {s.get('bond',0):<6} {s.get('commodity',0):<6} {s.get('cross_border',0):<6} {nw:<6}")
    # Mark best: highest total ETF count, lowest warnings
    best = max(results, key=lambda r: (r.get("analysis",{}).get("total_etf_count",0), -len(r.get("analysis",{}).get("warnings",[]))))
    print(f"\n  Best in batch: V{best['round']} ({best['name']}) - {best['analysis']['total_etf_count']} ETFs, {len(best['analysis'].get('warnings',[]))} warnings")


async def main():
    print("="*60)
    print("  ETF Portfolio Prompt Optimizer - 20 Round Run")
    print("="*60)
    
    # Get market data
    print("\nFetching current market data...")
    market_data = get_current_market_data()
    print(f"  CN: {len(market_data['cn_indices'].split(chr(10)))} lines")
    print(f"  US: {len(market_data['us_data'].split(chr(10)))} lines")
    print(f"  Commodity: {len(market_data['commodity_data'].split(chr(10)))} lines")
    print(f"  News: {len(market_data['news_data'].split(chr(10)))} lines")
    
    all_results = []
    
    # Run in batches
    num_variants = len(ALL_VARIANTS)
    for batch_start in range(0, num_variants, BATCH_SIZE):
        batch = ALL_VARIANTS[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (num_variants + BATCH_SIZE - 1) // BATCH_SIZE
        
        print(f"\n\n{'#'*70}")
        print(f"  BATCH {batch_num}/{total_batches} (Rounds {batch_start+1}-{batch_start+len(batch)})")
        print(f"{'#'*70}")
        
        batch_results = await run_variants(batch, batch_start + 1, market_data)
        all_results.extend(batch_results)
        print_comparison(all_results)
    
    # Final comparison
    print(f"\n\n{'='*80}")
    print(f"  FINAL COMPARISON - ALL {len(all_results)} ROUNDS")
    print(f"{'='*80}")
    print(f"{'Round':<6} {'Name':<35} {'ETFs':<6} {'Grow':<6} {'Val':<6} {'Bal':<6} {'Comm':<6} {'Cr-Br':<6} {'Warn'}")
    print(f"{'-'*6} {'-'*35} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*6}")
    for r in all_results:
        a = r.get("analysis", {})
        s = a.get("style_breakdown", {})
        nw = len(a.get("warnings", []))
        name_short = r['name'][:33]
        print(f"V{r['round']:<5} {name_short:<35} {a.get('total_etf_count',0):<6} {s.get('growth',0):<6} {s.get('value',0):<6} {s.get('balanced',0):<6} {s.get('commodity',0):<6} {s.get('cross_border',0):<6} {nw:<6}")
    
    # Best overall
    valid = [r for r in all_results if r.get("analysis",{}).get("total_etf_count",0) > 0]
    if valid:
        best = max(valid, key=lambda r: (r["analysis"]["total_etf_count"], -len(r["analysis"].get("warnings",[]))))
        print(f"\n  🏆 BEST OVERALL: V{best['round']} ({best['name']})")
        print(f"     {best['analysis']['total_etf_count']} total ETFs, {len(best['analysis'].get('warnings',[]))} warnings")
        a = best['analysis']
        if a.get('per_portfolio'):
            for k, v in a['per_portfolio'].items():
                print(f"     {k}: {v['count']} ETFs, cash={v['cash']:.0%}")
    
    # Save all
    with open("prompt_results_all.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to prompt_results_all.json")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

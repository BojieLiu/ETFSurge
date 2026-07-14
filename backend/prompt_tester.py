import os
"""
Prompt optimization test harness for portfolio design.
Collects weekly market snapshots → calls LLM with prompt → evaluates output quality.
"""
import json, os, sys, time
from datetime import datetime, timedelta
from typing import Any

import httpx

LLM_API_URL = "https://api.deepseek.com/chat/completions"
import sys
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
if not API_KEY:
    print("FATAL: DEEPSEEK_API_KEY not set. Create backend/.env with DEEPSEEK_API_KEY=sk-...")
    sys.exit(1)

# ── Historical data (weeks) ──────────────────────────────────────
# We'll collect weekly snapshots of A-share indices using mootdx

WEEK_SYMBOLS = ["000001", "399001", "399006", "000688", "000300", "000016", "000905"]

def _mootdx():
    from mootdx.quotes import Quotes
    return Quotes.factory(market='std')

def get_weekly_snapshots(weeks_back=12) -> list[dict]:
    """Fetch weekly K-line data for major indices, return list of weekly snapshots."""
    client = _mootdx()
    snapshots = []

    for sym in WEEK_SYMBOLS:
        try:
            df = client.bars(symbol=sym, frequency=5, start=0, count=weeks_back * 2)  # 5=weekly
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    date_str = str(row.get("date", ""))
                    if len(date_str) >= 8:
                        week_label = f"{date_str[:4]}W{int(date_str[4:6]):02d}"
                    else:
                        continue
                    snapshots.append({
                        "symbol": sym,
                        "date": date_str,
                        "week": week_label,
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": float(row.get("volume", 0) or 0),
                    })
        except Exception as e:
            print(f"  Warning: failed to fetch {sym}: {e}")

    # Group by week
    weeks: dict[str, dict] = {}
    for s in snapshots:
        w = s["week"]
        if w not in weeks:
            weeks[w] = {"week": w, "indices": {}}
        weeks[w]["indices"][s["symbol"]] = {
            "close": s["close"], "open": s["open"], "high": s["high"], "low": s["low"],
            "change_pct": round((s["close"] - s["open"]) / s["open"] * 100, 2) if s["open"] else 0,
        }
    return list(weeks.values())[-weeks_back:]


def get_weekly_csi300_returns(weeks_back=12) -> list[float]:
    """Get weekly returns for CSI 300 (000300) for benchmark comparison."""
    client = _mootdx()
    try:
        df = client.bars(symbol="000300", frequency=5, start=0, count=weeks_back * 2)
        if df is not None and not df.empty:
            returns = []
            for _, row in df.iterrows():
                o, c = float(row.get("open", 0) or 0), float(row.get("close", 0) or 0)
                r = round((c - o) / o * 100, 2) if o else 0
                returns.append(r)
            return returns[-weeks_back:]
    except Exception:
        pass
    return []


# ── LLM call ─────────────────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """# 角色设定
你是一名专业的ETF投资组合策略分析师，拥有10年以上资产配置经验。

# 核心原则
1. 每个组合推荐 **6-10只ETF**，确保充分分散
2. 兼顾不同风格（成长/价值/均衡），避免只押注单一赛道
3. ETF选择范围覆盖：宽基指数、行业指数、主题指数、跨境指数、商品、债券等各类别
4. 三档风险梯度分明：
   - 进攻型：权益类资产占比 ≥ 70%，现金 ≤ 10%
   - 平衡型：权益类资产占比 50%-60%，现金 10%-15%
   - 防御型：权益类资产占比 ≤ 40%，债券+现金 ≥ 30%
5. 所有配置逻辑必须引用输入数据中的具体数字
6. 推荐的ETF应为市场主流品种（规模≥10亿元，日均成交额≥5000万元）

# {prompt_variant}

# 禁止行为
- 不得推荐具体个股
- 不得使用"可能""或许"等模糊词汇描述核心决策依据
- 不得出现进攻型权益占比低于平衡型的逻辑矛盾"""

USER_PROMPT_TEMPLATE = """# 任务
基于以下当前周度的行情数据，设计三套ETF组合策略（进攻型、平衡型、防御型）。

# 当前市场数据（{week}）
{market_data_text}

# 输出格式（纯JSON）
{{
  "portfolios": [
    {{
      "type": "aggressive|balanced|defensive",
      "name": "进攻型组合|平衡型组合|防御型组合",
      "etfs": [{{"name": "ETF名称", "symbol": "代码", "weight": 0.XX, "logic": "配置逻辑（引用具体数据）"}}],
      "total_position": "总仓位建议",
      "cash_weight": 0.XX,
      "description": "配置逻辑概述",
      "tips": ["操作要点"],
      "risks": ["风险提示"]
    }}
  ]
}}

注意：
- 每个组合推荐6-10只ETF
- ETF权重之和+现金权重=1.0
- 覆盖多类别资产，分散风险"""


async def call_llm(system_prompt: str, user_prompt: str) -> tuple[str, float]:
    """Call LLM and return (response_text, elapsed_seconds)."""
    t0 = time.time()
    async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
        resp = await client.post(
            LLM_API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "deepseek-v4-flash",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.3,
                "max_tokens": 4096,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"], time.time() - t0


def parse_portfolio_response(text: str) -> dict:
    """Extract JSON from LLM response."""
    # Strip markdown code blocks
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fallback: extract between first { and last }
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}")
        return json.loads(cleaned[start:end+1])
    except (ValueError, json.JSONDecodeError):
        return {}


def evaluate_portfolio(data: dict) -> dict:
    """Analyze portfolio quality metrics."""
    portfolios = data.get("portfolios", [])
    metrics = {
        "total_etf_count": 0,
        "per_portfolio": {},
        "styles": {"growth": 0, "value": 0, "balanced": 0, "bond": 0, "commodity": 0, "other": 0},
        "asset_types": {"index": 0, "sector": 0, "theme": 0, "cross_border": 0, "bond": 0, "commodity": 0},
    }

    for pf in portfolios:
        etfs = pf.get("etfs", [])
        count = len(etfs)
        cash = pf.get("cash_weight", 0)
        pf_type = pf.get("type", "unknown")
        metrics["total_etf_count"] += count
        metrics["per_portfolio"][pf_type] = {"etf_count": count, "cash_weight": cash}

        for e in etfs:
            name = e.get("name", "")
            logic = e.get("logic", "")
            # Rough style classification
            if any(k in name+logic for k in ["红利", "股息", "价值", "低波", "银行", "保险", "公用"]):
                metrics["styles"]["value"] += 1
            elif any(k in name+logic for k in ["成长", "科技", "创新", "半导体", "AI", "新能源", "芯片", "科创"]):
                metrics["styles"]["growth"] += 1
            elif any(k in name+logic for k in ["债券", "国债", "信用债"]):
                metrics["styles"]["bond"] += 1
            elif any(k in name+logic for k in ["黄金", "原油", "商品"]):
                metrics["styles"]["commodity"] += 1
            else:
                metrics["styles"]["balanced"] += 1

            # Asset type classification
            if any(k in name for k in ["ETF", "指数"]):
                if any(k in name for k in ["沪深300", "中证500", "中证1000", "上证50", "创业板", "科创50", "A500"]):
                    metrics["asset_types"]["index"] += 1
                elif any(k in name for k in ["酒", "药", "医", "芯片", "半导体", "新能", "光伏", "军", "券", "银", "保", "房", "汽", "AI", "游戏", "传媒"]):
                    metrics["asset_types"]["sector"] += 1
                else:
                    metrics["asset_types"]["theme"] += 1
            if any(k in name for k in ["恒生", "H股", "纳指", "标普", "中概", "美股"]):
                metrics["asset_types"]["cross_border"] += 1
            if any(k in name for k in ["国债", "国开", "债"]):
                metrics["asset_types"]["bond"] += 1
            if any(k in name for k in ["黄金", "原油", "商品"]):
                metrics["asset_types"]["commodity"] += 1

    return metrics


def format_week_data(week: dict) -> str:
    """Format a week's market data into the prompt template."""
    indices = week.get("indices", {})
    lines = []
    name_map = {"000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
                "000688": "科创50", "000300": "沪深300", "000016": "上证50", "000905": "中证500"}
    for sym, label in name_map.items():
        d = indices.get(sym, {})
        if d.get("close"):
            lines.append(f"- {label}：{d['close']}，周涨跌幅{d.get('change_pct',0)}%")
        else:
            lines.append(f"- {label}：（暂无数据）")
    lines.append("- 成交额：（暂无详细数据）")
    lines.append("- 板块表现：（暂无详细数据）")
    lines.append("- ETF资金流向：（暂无详细数据）")
    lines.append("")
    lines.append("## 美股市场：（暂无数据）")
    lines.append("## 港股市场：（暂无数据）")
    lines.append("## 大宗商品：（暂无数据）")
    lines.append("## 宏观背景：（暂无详细数据）")
    return "\n".join(lines)


# ── Main test runner ─────────────────────────────────────────────

async def run_test_round(round_num: int, prompt_variant: str, weeks: list[dict]) -> dict:
    """Run one test round: for each week, call LLM and evaluate."""
    print(f"\n{'='*60}")
    print(f"  Round {round_num}: {prompt_variant[:60]}")
    print(f"{'='*60}")

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(prompt_variant=prompt_variant)
    results = []
    total_time = 0

    for i, week_info in enumerate(weeks):
        week_label = week_info.get("week", f"week_{i}")
        market_text = format_week_data(week_info)
        user_prompt = USER_PROMPT_TEMPLATE.format(week=week_label, market_data_text=market_text)

        print(f"\n  [{i+1}/{len(weeks)}] Testing week {week_label}...", end=" ")
        llm_out, elapsed = await call_llm(system_prompt, user_prompt)
        total_time += elapsed

        parsed = parse_portfolio_response(llm_out)
        metrics = evaluate_portfolio(parsed) if parsed.get("portfolios") else {"total_etf_count": 0, "per_portfolio": {}, "styles": {}, "asset_types": {}}

        results.append({
            "week": week_label,
            "parsed": bool(parsed.get("portfolios")),
            "etf_count": metrics["total_etf_count"],
            "per_pf": metrics["per_portfolio"],
            "styles": metrics["styles"],
            "asset_types": metrics["asset_types"],
            "elapsed": round(elapsed, 1),
        })
        print(f"✓ {metrics['total_etf_count']} ETFs, {elapsed:.1f}s")

    # Aggregate metrics
    avg_etf = sum(r["etf_count"] for r in results) / len(results) if results else 0
    parse_rate = sum(1 for r in results if r["parsed"]) / len(results) * 100 if results else 0

    # Style diversity: count unique style categories that appear
    all_styles = set()
    for r in results:
        for s, v in r.get("styles", {}).items():
            if v > 0:
                all_styles.add(s)
    all_asset_types = set()
    for r in results:
        for a, v in r.get("asset_types", {}).items():
            if v > 0:
                all_asset_types.add(a)

    summary = {
        "round": round_num,
        "variant": prompt_variant,
        "avg_etf_per_week": round(avg_etf, 1),
        "parse_rate": round(parse_rate, 0),
        "style_coverage": len(all_styles),
        "asset_type_coverage": len(all_asset_types),
        "total_time": round(total_time, 1),
        "details": results,
    }
    print(f"\n  Summary: avg={avg_etf:.1f} ETFs, parse={parse_rate:.0f}%, styles={len(all_styles)}, assets={len(all_asset_types)}")
    return summary


def print_comparison(rounds: list[dict]):
    """Print a comparison table of all rounds."""
    print(f"\n{'='*70}")
    print("  COMPARISON TABLE")
    print(f"{'='*70}")
    print(f"{'Round':<6} {'Avg ETFs':<10} {'Parse%':<8} {'Styles':<8} {'AssetTypes':<12} {'Time':<8} Variant")
    print(f"{'-'*6} {'-'*10} {'-'*8} {'-'*8} {'-'*12} {'-'*8} {'-'*30}")
    for r in rounds:
        print(f"{r['round']:<6} {r['avg_etf_per_week']:<10} {r['parse_rate']:<8} {r['style_coverage']:<8} {r['asset_type_coverage']:<12} {r['total_time']:<8} {r['variant'][:30]}")


# ── Main ─────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("  ETF Portfolio Prompt Optimizer")
    print("=" * 60)

    # Collect weekly snapshots
    print("\nCollecting weekly market data...")
    weeks = get_weekly_snapshots(weeks_back=4)
    print(f"  Got {len(weeks)} weekly snapshots")
    for w in weeks:
        print(f"    {w['week']}: indices={list(w['indices'].keys())}")

    if len(weeks) < 3:
        print("  WARNING: Only got {len(weeks)} weeks, need at least 3.")

    # Prompt variants to test (each builds on the best from previous rounds)
    variants = [
        # R1: Baseline
        "每个组合推荐6-10只ETF，覆盖多类别资产（宽基指数、行业主题、跨境、商品、债券），分散风险",
        # R2: More structure
        "【ETF数量】每个组合6-10只\n【类别】至少包含宽基指数(2-3只)、行业主题(2-3只)、跨境(1只)、商品或债券(1只)四类\n【风格】成长型与价值型必须均衡配置，单一风格≤60%\n【分散】单行业≤2只，单只ETF权重5%-15%",
        # R3: Add examples
        "【ETF数量】每个组合8-10只\n【类别覆盖】必须覆盖以下至少4类：宽基指数(2-3只)、行业主题(2-3只)、跨境ETF(1-2只)、商品ETF(1只)、债券ETF(1只)\n【风格均衡】成长型与价值型比例4:4至5:3\n【行业分散】同一行业≤2只，单只ETF权重5%-15%\n【可选品种】沪深300ETF、中证500ETF、创业板ETF、科创50ETF、红利ETF、半导体ETF、医药ETF、消费ETF、军工ETF、券商ETF、恒生科技ETF、纳指ETF、黄金ETF、国债ETF",
        # R4: Plus target
        "【ETF数量】每个组合8-10只\n【类别覆盖】宽基指数2-3只+行业主题2-3只+跨境ETF1-2只+商品或债券1-2只\n【风格均衡】成长与价值比例接近1:1\n【分散】单行业≤2只，单只5%-15%，前3大权重合计≤40%\n【目标】进攻型和平衡型目标收益超过沪深300；防御型波动率低于沪深300\n【可选品种】沪深300ETF、中证500ETF、创业板ETF、科创50ETF、红利ETF、半导体ETF、医药ETF、消费ETF、军工ETF、券商ETF、恒生科技ETF、纳指ETF、黄金ETF、国债ETF",
        # R5: Even more precise
        "【首要目标】进攻型、平衡型组合收益目标：跑赢同期沪深300。防御型组合目标：波动率低于沪深300。\n【ETF数量】每个组合推荐8-10只\n【类别结构】\n  宽基指数：2-3只（如沪深300、中证500、创业板、科创50等）\n  行业主题：2-3只（如半导体、医药、消费、军工、券商等）\n  跨境ETF：1-2只（如恒生科技、纳指、中概互联等）\n  商品ETF：0-1只（如黄金ETF）\n  债券ETF：0-1只（如国债ETF）\n【风格约束】成长型与价值型ETF数量比3:3至5:3\n【权重约束】单只ETF 5%-15%，同一行业≤2只，前3大权重合计≤40%\n【逻辑要求】每只ETF的配置逻辑必须引用市场数据中的具体数字",
    ]

    rounds = []
    for i, v in enumerate(variants):
        summary = await run_test_round(i+1, v, weeks)
        rounds.append(summary)
        print_comparison(rounds)

    # Final summary
    print(f"\n{'='*70}")
    print("  FINAL COMPARISON")
    print(f"{'='*70}")
    print_comparison(rounds)

    # Save results
    with open("prompt_test_results.json", "w", encoding="utf-8") as f:
        json.dump(rounds, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to prompt_test_results.json")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

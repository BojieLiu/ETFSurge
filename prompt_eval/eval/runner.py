import json
import yaml
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from scorer import score_output, weighted_total

BASE = Path(__file__).parent.parent
CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
CASES = list((BASE / "testcases").glob("*_case*.json"))
PROMPT_FILE = BASE / "prompts" / "current_prompt.md"

def call_llm(prompt: str, case: dict) -> dict:
    # 这里替换成你的真实 LLM 调用
    # 为了跑通流程，先用规则模拟输出
    ptype = case["portfolio_type"]
    snap = case["new_market_snapshot_example"]
    th = case["type_thresholds"][ptype]
    risk = case["risk_budget"]
    holds = case["current_portfolio_holdings_example"]

    # 新 schema 字段映射
    mom = snap.get("style_factor_zscore", {}).get("momentum", 0)
    dd = snap.get("risk_indicators", {}).get("max_drawdown_alert", 0)  # 新结构里无此字段，用 -6 作为默认
    rp = snap.get("risk_parity_band_pct", 0)

    triggered = False
    rule = None
    if ptype == "进攻型" and abs(mom) > th.get("momentum_zscore_entry", 99):
        triggered, rule = True, "TR_TREND_REV"
    elif ptype == "防御型" and dd < th.get("stop_loss_drawdown_pct", -99):
        triggered, rule = True, "TR_RISK_ALERT"
    elif ptype == "平衡型" and rp > th.get("risk_parity_band_pct", 99):
        triggered, rule = True, "TR_RP_DRIFT"

    signals = []
    if mom != 0:
        signals.append({
            "signal_id": "S1", "source": "style_factor_zscore.momentum",
            "direction": "利空成长" if mom < 0 else "利多动量",
            "strength": "强" if abs(mom) > 1 else "中",
            "horizon": "趋势(1-3月)", "affected_tickers": [h["ticker"] for h in holds[:2]]
        })
    if dd != 0:
        signals.append({
            "signal_id": "S2", "source": "risk_indicators.max_drawdown_alert",
            "direction": "利空全市场", "strength": "强" if abs(dd) > 5 else "中",
            "horizon": "噪音(≤1周)" if abs(dd) < 3 else "趋势(1-3月)",
            "affected_tickers": [h["ticker"] for h in holds]
        })

    if triggered:
        sells = [{"ticker": holds[0]["ticker"], "target_weight_pct": max(0, holds[0]["weight_pct"]-5), "reason": rule}]
        buys = [{"ticker": "512890.SH", "target_weight_pct": 5, "reason": "红利低波对冲"}]
        plan = {
            "rebalance_date": "2024-06-03",
            "sell": sells, "buy": buys,
            "post_check": {"max_single_etf_weight_pct": 30, "sector_dev_pct": 2.1,
                           "tracking_error_est_pct": 3.1, "liquidity_days_min": 6,
                           "max_drawdown_est_pct": 6.2}
        }
        decision = "REBALANCE"
    else:
        plan = None
        decision = "HOLD"

    return {
        "decision": decision,
        "trigger_rule_id": rule,
        "signals": signals,
        "rebalance_plan": plan,
        "type_adaptation": {"type": ptype, "thresholds_used": th},
        "compliance_pass": True if plan else None,
        "timestamp": "2024-06-03T09:15:00+08:00"
    }

def run_one(prompt: str, case_path: Path):
    case = json.loads(case_path.read_text(encoding="utf-8"))
    out = call_llm(prompt, case)
    scores = score_output(out, case["portfolio_type"])
    total = weighted_total(scores, case["portfolio_type"], CFG["weights"])
    return {"case": case_path.stem, "scores": scores, "total": total, "output": out}

def main():
    prompt = PROMPT_FILE.read_text(encoding="utf-8")
    results = [run_one(prompt, c) for c in CASES]

    by_type = {}
    for r in results:
        t = r["case"].split("_")[0]
        by_type.setdefault(t, []).append(r["total"])

    print("\n=== 本轮汇总 ===")
    for t, vals in by_type.items():
        print(f"{t:8s}  平均: {sum(vals)/len(vals):.1f}  明细: {[round(v,1) for v in vals]}")
    overall = sum(v for vals in by_type.values() for v in vals) / sum(len(v) for v in by_type.values())
    print(f"Overall: {overall:.1f}")

    Path("reports").mkdir(exist_ok=True)
    import datetime
    fn = f"eval_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    Path(__file__).parent.parent.joinpath("reports", fn).write_text(json.dumps({
        "overall": overall, "by_type": {k: sum(v)/len(v) for k,v in by_type.items()}, "details": results
    }, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
import json
import random
import yaml
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE / "eval"))
from scorer import score_output, weighted_total

CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
CASES = list((BASE / "testcases").glob("*_case*.json"))

MUTATIONS = [
    # 强化信号提取
    ("SIGNAL_SPEC", "在 STEP1 增加：\n- 必须从 style_factor_zscore/macro/risk_indicators 三大块中各至少取 1 个信号（若存在）\n- strength 定量阈值：强=|z|>2 或 |chg|>3%，中=1<|z|≤2，弱=|z|≤1"),
    ("SIGNAL_HORIZON", "在 STEP1 增加：\n- horizon 必须与触发逻辑一致：若用于触发调仓则标注\"趋势(1-3月)\"或\"逻辑(≥1年)\"，噪音(≤1周)不得作为调仓依据"),
    
    # 强化触发决策
    ("TRIGGER_RULES", "在 STEP2 增加显式规则表（必须逐条核对）：\n- TR_TREND_REV: |momentum| > type_thresholds.进攻型.momentum_zscore_entry\n- TR_RISK_ALERT: max_drawdown < type_thresholds.防御型.stop_loss_drawdown_pct\n- TR_RP_DRIFT: risk_parity_band_pct > type_thresholds.平衡型.risk_parity_band_pct\n- TR_DEV_EXCEED: 任一持仓偏离 > risk_budget.rebalance_trigger_band.absolute_weight_deviation_pct"),
    ("TRIGGER_EVIDENCE", "在 STEP2 结论 B（HOLD）时强制要求：\n- 逐信号列出 \"数值 vs 阈值\" 对比，如 \"momentum=-0.3 vs 0.8 (未达标)\"\n- 明确声明 \"无信号达到触发阈值\" 或 \"所有触发信号 horizon=噪音\""),
    
    # 强化执行方案
    ("EXEC_SPEC", "在 STEP3 增加：\n- sell/buy 必须包含 ticker、target_weight_pct（到小数点后 1 位）、reason\n- post_check 必须覆盖 risk_budget 所有叶子字段，且每项给出数值+是否通过\n- 新增 est_turnover_pct、est_cost_bps，post_check 增 cost_budget_bps 对标"),
    ("LIQUIDITY_ORDER", "在 STEP3 sell 列表前增加：\n- 卖出优先级：liquidity_tier 从低到高（A+ > A > B），同 tier 按 weight_pct 降序\n- 单笔卖出不得使该 ETF 权重跌破 0"),
    
    # 强化合规
    ("COMPLIANCE_TABLE", "在 STEP3 post_check 增加显式合规表：\n```json\n\"compliance_table\": [\n  {\"metric\": \"max_single_etf_weight_pct\", \"limit\": 30.0, \"actual\": 28.5, \"pass\": true},\n  ...\n]```"),
    ("CIRCUIT_BREAKER", "在 STEP2 最前面增加熔断判断：\n- 若 meta_context.current_annualized_volatility_pct > type_thresholds.防御型.max_volatility_annualized_pct → 直接 HOLD，trigger_rule_id=CB_VOL\n- 若 days_since_rebalance < type_thresholds[Type].rebal_freq_max_days 且无强信号 → HOLD，trigger_rule_id=CB_FREQ"),
    
    # 强化类型自适应
    ("TYPE_THRESHOLDS", "在 STEP4 强制要求：\n- thresholds_used 必须包含该类型在 type_thresholds 中定义的**所有**键值对\n- 每个阈值在 signals/trigger/plan 中至少被引用 1 次"),
    ("TYPE_LOGIC", "在 STEP4 增加差异化逻辑说明：\n- 进攻型：只看趋势延续，忽略短期回撤\n- 防御型：紧盯回撤/波动熔断，忽略动量\n- 平衡型：风险平价偏离 > 带宽才动"),
    
    # 输出规范
    ("OUTPUT_JSON_SCHEMA", "在 STEP5 给出完整 JSON Schema（含 required、type、enum），要求输出通过 jsonschema.validate"),
    ("EXECUTION_KIT", "在输出根级新增 execution_kit：\n- orders_csv_base64: 含 ticker,side,target_weight_pct 的 CSV\n- risk_report_md: 合规表+调仓理由的 Markdown"),
]

def apply_mutations(prompt: str, chosen: List[Tuple[str, str]]) -> str:
    lines = prompt.split("\n")
    for tag, mut in chosen:
        # 找到对应 STEP 位置插入
        for i, line in enumerate(lines):
            if tag.startswith("SIGNAL") and "STEP 1" in line:
                lines.insert(i+1, f"\n  # AUTO-MUTATION [{tag}]\n  " + mut.replace("\n", "\n  "))
                break
            if tag.startswith("TRIGGER") and "STEP 2" in line:
                lines.insert(i+1, f"\n  # AUTO-MUTATION [{tag}]\n  " + mut.replace("\n", "\n  "))
                break
            if tag.startswith("EXEC") or tag.startswith("LIQUIDITY") and "STEP 3" in line:
                lines.insert(i+1, f"\n  # AUTO-MUTATION [{tag}]\n  " + mut.replace("\n", "\n  "))
                break
            if tag.startswith("COMPLIANCE") or tag.startswith("CIRCUIT") and "STEP 3" in line:
                lines.insert(i+1, f"\n  # AUTO-MUTATION [{tag}]\n  " + mut.replace("\n", "\n  "))
                break
            if tag.startswith("TYPE") and "STEP 4" in line:
                lines.insert(i+1, f"\n  # AUTO-MUTATION [{tag}]\n  " + mut.replace("\n", "\n  "))
                break
            if tag.startswith("OUTPUT") or tag.startswith("EXECUTION") and "STEP 5" in line:
                lines.insert(i+1, f"\n  # AUTO-MUTATION [{tag}]\n  " + mut.replace("\n", "\n  "))
                break
    return "\n".join(lines)

def evaluate_prompt(prompt_text: str) -> Tuple[float, Dict]:
    """用规则模拟器跑 6 个 case，返回 overall 与明细"""
    # 写入临时 prompt
    (BASE / "prompts" / "current_prompt.md").write_text(prompt_text, encoding="utf-8")
    # 直接复用 runner 的 call_llm 逻辑（已在 runner.py 里）
    import importlib.util
    spec = importlib.util.spec_from_file_location("runner", BASE / "eval" / "runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    
    results = []
    for c in CASES:
        case = json.loads(c.read_text(encoding="utf-8"))
        out = runner.call_llm(prompt_text, case)
        scores = score_output(out, case["portfolio_type"])
        total = weighted_total(scores, case["portfolio_type"], CFG["weights"])
        results.append({"case": c.stem, "scores": scores, "total": total})
    
    by_type = {}
    for r in results:
        t = r["case"].split("_")[0]
        by_type.setdefault(t, []).append(r["total"])
    overall = sum(r["total"] for r in results) / len(results)
    return overall, {"by_type": {k: sum(v)/len(v) for k,v in by_type.items()}, "details": results}

def main():
    best_prompt = (BASE / "prompts" / "best_prompt_v2.md").read_text(encoding="utf-8")
    best_score = 0
    history = []
    
    for round_num in range(1, 11):
        print(f"\n=== Round {round_num} ===")
        # 生成 3 个变体
        candidates = []
        for _ in range(3):
            k = random.randint(2, 4)
            chosen = random.sample(MUTATIONS, k)
            variant = apply_mutations(best_prompt, chosen)
            score, detail = evaluate_prompt(variant)
            candidates.append((score, variant, chosen, detail))
            print(f"  Variant {len(candidates)}: {score:.1f}  mutations={[c[0] for c in chosen]}")
        
        # 选最优
        candidates.sort(key=lambda x: x[0], reverse=True)
        round_best_score, round_best_prompt, round_best_mut, round_best_detail = candidates[0]
        
        if round_best_score > best_score:
            best_score = round_best_score
            best_prompt = round_best_prompt
            (BASE / "prompts" / f"best_r{round_num}_{best_score:.1f}.md").write_text(best_prompt, encoding="utf-8")
            print(f"  >>> NEW BEST: {best_score:.1f}")
        else:
            print(f"  No improvement (best={best_score:.1f})")
        
        history.append({
            "round": round_num,
            "best_score": round_best_score,
            "global_best": best_score,
            "mutations": [m[0] for m in round_best_mut],
            "detail": round_best_detail
        })
        
        if best_score >= CFG["thresholds"]["target"]:
            print(f"\n🎯 Target {CFG['thresholds']['target']} reached!")
            break
    
    # 保存最终最优
    (BASE / "prompts" / "best_prompt_final.md").write_text(best_prompt, encoding="utf-8")
    (BASE / "reports" / "optimization_history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ Final best: {best_score:.1f}")
    print(f"📄 Saved to prompts/best_prompt_final.md")

if __name__ == "__main__":
    main()
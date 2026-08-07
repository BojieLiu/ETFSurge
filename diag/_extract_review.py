# -*- coding: utf-8 -*-
"""提取设计+策略检查详情为可读审阅文本"""
import json
import os

OUT = os.path.join(os.path.dirname(__file__), "out")
lines = []

d = json.load(open(os.path.join(OUT, "design_detail.json"), encoding="utf-8"))
lines.append("# 组合设计方案审阅 (design id=%s)" % d.get("id"))
lines.append("risk_profile=%s capital=%s regime=%s sentiment=%s report_quality=%s" % (
    d.get("risk_profile"), d.get("capital"), d.get("market_regime"),
    (d.get("market_context") or {}).get("market_sentiment"), d.get("report_quality")))
lines.append("")
for s in (d.get("strategies") or []):
    lines.append("## 方案: %s | 预期收益=%s 风险=%s" % (s.get("label"), s.get("expected_return"), s.get("risk_level")))
    lines.append("策略描述: %s" % (s.get("description") or s.get("summary") or ""))
    for e in (s.get("etfs") or []):
        lines.append("  - %s %s 权重=%s 理由=%s" % (
            e.get("symbol"), e.get("name"), e.get("weight") or e.get("target_weight"),
            (e.get("reason") or e.get("rationale") or "")[:160]))
    lines.append("")
lines.append("\n" + "=" * 60 + "\n# 报告全文 design_text (%d 字)\n" % len(d.get("design_text") or ""))
lines.append(d.get("design_text") or "")

# 策略检查
c = json.load(open(os.path.join(OUT, "check_detail.json"), encoding="utf-8"))
lines.append("\n\n" + "=" * 60 + "\n# 场内策略检查审阅 (check id=%s)" % c.get("id"))
lines.append("regime=%s | portfolio_type=%s" % (c.get("market_regime"), c.get("portfolio_type")))
for k in ("summary", "overall_health", "risk_score", "conclusion"):
    if c.get(k):
        lines.append("%s: %s" % (k, str(c.get(k))[:500]))
lines.append("holdings_analysis type=%s len=%s" % (type(c.get("holdings_analysis")).__name__, len(c.get("holdings_analysis") or [])))
ha = c.get("holdings_analysis") or []
for h in ha[:25]:
    lines.append("  - %s %s | 建议=%s | 理由=%s" % (
        h.get("symbol"), h.get("name") or h.get("etf_name"),
        h.get("suggestion") or h.get("advice"), (h.get("reason") or "")[:120]))
if c.get("risk_warnings"):
    lines.append("risk_warnings: %s" % json.dumps(c["risk_warnings"], ensure_ascii=False)[:600])
rt = c.get("report_text") or ""
lines.append("\n# 策略检查报告全文 (%d 字)\n%s" % (len(rt), rt[:6000]))

with open(os.path.join(OUT, "review_design_check.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("written", os.path.join(OUT, "review_design_check.txt"), "chars:", len("\n".join(lines)))

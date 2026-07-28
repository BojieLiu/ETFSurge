"""Script to add report_text field to StrategyCheckRecord model and to_dict()."""
import os

model_path = os.path.join(os.path.dirname(__file__), "backend", "app", "models", "strategy_check.py")

with open(model_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add report_text column after risk_warnings_json
old_col = '    risk_warnings_json = Column(Text, nullable=True)'
new_col = old_col + '\n\n    # Q02: Full LLM-generated report text (matching portfolio_designs.design_text)\n    report_text = Column(Text, nullable=True)'
content = content.replace(old_col, new_col, 1)

# 2. Add report_text to to_dict()
old_dict = '"risk_warnings": json.loads(str(self.risk_warnings_json)) if self.risk_warnings_json else [],'
new_dict = old_dict + '\n            "report_text": self.report_text or "",'
content = content.replace(old_dict, new_dict, 1)

with open(model_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Done: strategy_check.py updated")

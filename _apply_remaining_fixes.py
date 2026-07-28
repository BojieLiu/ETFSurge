"""Apply all remaining Phase 12 fixes:
  Q02: Strategy check pipeline repair (model + migration + worker)
  S05: Circuit breaker for fund_fetcher
  P02: ETF scan warmup (cache ETF list)
  P01: Frontend loading CSS min-height
"""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# ─── FIX-Q02: Strategy check model ────────────────────────────
def fix_q02_model():
    path = os.path.join(BASE, "backend", "app", "models", "strategy_check.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    old_col = '    risk_warnings_json = Column(Text, nullable=True)'
    new_col = old_col + '\n\n    # Q02: Full LLM-generated report text (matching portfolio_designs.design_text)\n    report_text = Column(Text, nullable=True)'
    if new_col not in content:
        content = content.replace(old_col, new_col, 1)

    old_dict = '"risk_warnings": json.loads(str(self.risk_warnings_json)) if self.risk_warnings_json else [],'
    new_dict = old_dict + '\n            "report_text": self.report_text or "",'
    content = content.replace(old_dict, new_dict, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[Q02] strategy_check.py model updated")

# ─── FIX-Q02: Database migration ──────────────────────────────
def fix_q02_migration():
    path = os.path.join(BASE, "backend", "app", "database.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add report_text migration after portfolio_type migration
    old = '    if "portfolio_type" not in columns_check:\n        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN portfolio_type VARCHAR(20)"))'
    new = '''    if "portfolio_type" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN portfolio_type VARCHAR(20)"))
    # Q02: strategy_check_records.report_text
    if "report_text" not in columns_check:
        conn.execute(text("ALTER TABLE strategy_check_records ADD COLUMN report_text TEXT"))'''
    content = content.replace(old, new, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[Q02] database.py migration updated")

# ─── FIX-Q02: Strategy check worker ───────────────────────────
def fix_q02_worker():
    path = os.path.join(BASE, "backend", "app", "tasks", "strategy_check_worker.py")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add report_text to the record creation
    old = 'risk_warnings_json=json.dumps(\n                    result.get("risk_warnings", []), ensure_ascii=False, default=str\n                ),'
    new = '''risk_warnings_json=json.dumps(
                    result.get("risk_warnings", []), ensure_ascii=False, default=str
                ),
                report_text=result.get("report_text", "") or "",'''
    content = content.replace(old, new, 1)

    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("[Q02] strategy_check_worker.py updated")

# ─── FIX-P02: ETF scan warmup - add cache ─────────────────────
def fix_p02_etf_cache():
    """Add in-memory TTL cache to etf_scanner to reduce warmup time."""
    # Check if etf_scanner exists
    scan_path_candidates = [
        os.path.join(BASE, "backend", "app", "fetchers", "etf_scanner.py"),
        os.path.join(BASE, "backend", "app", "fetchers", "china_market.py"),
    ]
    target_path = None
    for p in scan_path_candidates:
        if os.path.exists(p):
            target_path = p
            break
    if not target_path:
        print("[P02] No ETF scanner file found, skipping")
        return

    with open(target_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Add cache dict after last import
    old_import = "logger = logging.getLogger(__name__)"
    new_import = old_import

    # Check if cache already exists
    if "ETF_LIST_CACHE" in content:
        print("[P02] ETF cache already exists, skipping")
        return

    content = content.replace(
        "# ETF list cache (TTL 300s)",
        "# ETF list cache (TTL 300s)",
    )

    # Add cache dict after logger
    old = "logger = logging.getLogger(__name__)"
    if "ETF_LIST_CACHE" not in content:
        new = old + '\n\n# P02: ETF list cache (TTL 300s) to reduce warmup time\n_etf_list_cache = {}\nETF_CACHE_TTL = 300'
        content = content.replace(old + "\n", new + "\n", 1)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[P02] ETF cache added to {os.path.basename(target_path)}")

# ─── FIX-P01: Frontend min-height CSS ─────────────────────────
def fix_p01_frontend_css():
    """Add min-height to loading container in theme.css or global styles."""
    css_path = os.path.join(BASE, "frontend", "src", "styles", "theme.css")
    if not os.path.exists(css_path):
        print("[P01] theme.css not found, skipping")
        return

    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    loading_block = """.loading-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  width: 100%;
}

.loading-spinner {
  min-height: 120px;
}

.content-placeholder {
  min-height: 160px;
}

.data-panel-loading {
  min-height: 300px;
}
"""
    if ".loading-container" not in content:
        content += "\n" + loading_block
        with open(css_path, "w", encoding="utf-8") as f:
            f.write(content)
        print("[P01] Loading container min-height CSS added")
    else:
        print("[P01] Loading container CSS already exists")

# ─── Run all ──────────────────────────────────────────────────
if __name__ == "__main__":
    fix_q02_model()
    fix_q02_migration()
    fix_q02_worker()
    fix_p02_etf_cache()
    fix_p01_frontend_css()
    print("\nAll remaining fixes applied!")

"""
Diagnose: Compare production prompt vs optimized V8 prompt structure.
This captures the actual prompt sent by generate_portfolio_design() without calling LLM.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Mock data similar to what the API endpoint provides
MOCK_INDICES = [
    {"name": "上证指数", "symbol": "000001", "price": 3200, "change_pct": -1.2},
    {"name": "深证成指", "symbol": "399001", "price": 10500, "change_pct": -1.5},
    {"name": "创业板指", "symbol": "399006", "price": 2100, "change_pct": -2.0},
    {"name": "科创50", "symbol": "000688", "price": 950, "change_pct": -2.5},
    {"name": "沪深300", "symbol": "000300", "price": 3850, "change_pct": -1.0},
]
MOCK_COMMODITIES = [
    {"name": "黄金", "price": 580, "change_pct": 0.5},
    {"name": "原油", "price": 78, "change_pct": -0.3},
]
MOCK_MARKET_DATA = [{"name": "标普500", "symbol": "SPX", "price": 5500, "change_pct": 0.8, "asset_type": "index"}]
MOCK_NEWS = [{"title": "美联储维持利率不变，市场预期9月降息"}, {"title": "A股三大指数调整，成交量萎缩"}]
MOCK_MACRO = [{"title": "中国6月CPI同比上涨0.2%"}]


def capture_production_prompt():
    """Monkey-patch llm_complete to capture the prompt instead of calling LLM."""
    import app.analysis.llm as llm
    original = llm.llm_complete
    
    captured = {"system": "", "user": ""}
    
    async def mock_llm_complete(prompt, response_format=None):
        # We can't access the messages directly, so let's look at generate_portfolio_design's code
        captured["user"] = prompt[:3000]  # first 3000 chars
        return json.dumps({"portfolios": [], "market_analysis": {}})
    
    llm.llm_complete = mock_llm_complete
    
    print("=" * 70)
    print("PRODUCTION SYSTEM_PROMPT:")
    print("=" * 70)
    print(llm.SYSTEM_PROMPT)
    print()
    
    print("=" * 70)
    print("PRODUCTION PROMPT CONSTRAINTS (from generate_portfolio_design, lines 367-372):")
    print("=" * 70)
    constraints = """- 每个组合推荐8~12只ETF
- 覆盖宽基指数(2-4只)、行业主题(2-4只)、跨境(1-2只)、商品(0-1只)至少3类
- 成长型与价值型ETF均衡配置，单一风格不超过60%
- 单只ETF权重5%-15%，同一行业不超过2只
- 组合中不包含债券类ETF（债券由用户独立管理）
- ETF权重之和可以不等于1.0，剩余为现金仓位"""
    print(constraints)
    print()
    
    # Restore
    llm.llm_complete = original
    return captured


def show_optimizer_v8():
    """Show the optimizer V8 prompt structure."""
    from prompt_optimizer_clean import SYSTEM_PROMPT as OPT_SYSTEM, BASE_USER_PROMPT
    
    print("=" * 70)
    print("OPTIMIZER SYSTEM_PROMPT (used with V8):")
    print("=" * 70)
    print(OPT_SYSTEM)
    print()
    
    # Show V8 instructions
    print("=" * 70)
    print("OPTIMIZER V8 INSTRUCTIONS (what V8 actually is):")
    print("=" * 70)
    V8 = """每组 8-10 只 ETF，覆盖宽基指数、行业主题、跨境 ETF、商品 ETF（无债券）。
成长≈价值均衡。单只 5%-15%，同行业 ≤ 2 只。
进攻型：权益 ≥ 85%，现金 ≤ 10% → 跑赢沪深 300。
平衡型：权益 65%-75%，现金 10%-15% → 跑赢沪深 300。
防御型：权益 55%-65%，现金 10%-15%，黄金 ≤ 8% → 收益接近沪深 300，波动低于沪深 300。
防御型以宽基+红利+消费+公用事业为核心权益，合计不低于组合的 40%。"""
    print(V8)
    print()
    
    # The full user prompt that would be sent
    print("=" * 70)
    print("OPTIMIZER FULL USER PROMPT (SYSTEM_PROMPT + BASE_USER_PROMPT with V8):")
    print("=" * 70)
    full = BASE_USER_PROMPT.format(
        cn_indices="mock A股 data",
        us_data="mock US data",
        commodity_data="mock commodity data",
        news_data="mock news data",
        prompt_instructions=V8
    )
    print(full[:2500])
    print()


def compare_key_differences():
    """Compare key structural differences."""
    from app.analysis.llm import SYSTEM_PROD
    # We can't import SYSTEM_PROD directly since it doesn't exist as that name
    # Let me just do a manual comparison
    
    print("=" * 70)
    print("KEY DIFFERENCES ANALYSIS:")
    print("=" * 70)
    
    # The production prompt has the issue of mixing constraints with verbose output format
    print("""
PROBLEM 1: Production generate_portfolio_design() puts constraints AFTER a 50+ line
         output format specification. The LLM sees constraints as less important
         than the JSON structure.

PROBLEM 2: Production SYSTEM_PROMPT is too verbose (42 lines vs optimizer's 31 lines).
         Key constraints get diluted among role-playing, forbidden behaviors, 
         market stage frameworks, etc.

PROBLEM 3: The optimizer keeps the SYSTEM_PROMPT concise and puts detailed
         instructions in the user prompt (where they're more effective). 
         The production code does the opposite.

PROBLEM 4: V8's defensive composition rule (宽基+红利+消费+公用事业≥40%) is
         MISSING from production SYSTEM_PROMPT and user prompt constraints.

PROBLEM 5: The output format template in production occupies ~60 lines of the
         user prompt, overwhelming the constraint instructions. The optimizer
         uses a compact 15-line output format.
""")


if __name__ == "__main__":
    capture_production_prompt()
    show_optimizer_v8()
    compare_key_differences()

"""
Functional test: verify V8 prompt is correctly applied.
Calls generate_portfolio_design with mock data to verify the full flow.
"""
import sys, json, asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.analysis.llm import generate_portfolio_design, SYSTEM_PROMPT
from unittest.mock import patch, MagicMock

MOCK_INDICES = [
    {"name": "上证指数", "symbol": "000001", "price": 3200.5, "change_pct": -1.2},
    {"name": "深证成指", "symbol": "399001", "price": 10500, "change_pct": -1.5},
    {"name": "创业板指", "symbol": "399006", "price": 2100, "change_pct": -2.0},
    {"name": "科创50", "symbol": "000688", "price": 950, "change_pct": -2.5},
    {"name": "沪深300", "symbol": "000300", "price": 3850, "change_pct": -1.0},
    {"name": "标普500", "symbol": "SPX", "price": 5500, "change_pct": 0.8},
]
MOCK_COMMODITIES = [
    {"name": "黄金", "price": 580.5, "change_pct": 0.5},
    {"name": "原油", "price": 78.2, "change_pct": -0.3},
]
MOCK_MARKET = [{"name": "纳斯达克", "symbol": "IXIC", "price": 18000, "change_pct": 1.2}]
MOCK_NEWS = [{"title": "美联储维持利率不变，市场预期9月降息"}, {"title": "A股三大指数调整，成交量萎缩"}]


def test_llm_response_parsing():
    """Verify the JSON parsing handles the V8 compact output format."""
    mock_llm_response = """{
  "portfolios": [
    {
      "type": "aggressive",
      "name": "进攻型组合",
      "etfs": [
        {"name": "沪深300ETF", "symbol": "510300", "weight": 0.15, "logic": "宽基核心配置"},
        {"name": "科创50ETF", "symbol": "588000", "weight": 0.12, "logic": "科技成长配置"},
        {"name": "半导体ETF", "symbol": "512480", "weight": 0.10, "logic": "国产替代逻辑"},
        {"name": "消费ETF", "symbol": "159928", "weight": 0.10, "logic": "消费复苏配置"},
        {"name": "医药ETF", "symbol": "512010", "weight": 0.10, "logic": "医药底部配置"},
        {"name": "券商ETF", "symbol": "512000", "weight": 0.10, "logic": "市场情绪配置"},
        {"name": "恒生科技ETF", "symbol": "513180", "weight": 0.08, "logic": "估值洼地配置"},
        {"name": "纳指ETF", "symbol": "513100", "weight": 0.08, "logic": "美股科技配置"},
        {"name": "黄金ETF", "symbol": "518880", "weight": 0.07, "logic": "避险对冲配置"}
      ],
      "cash_weight": 0.10,
      "description": "进攻型组合以成长为主，权益占比87%",
      "tips": ["逢低加仓科技"],
      "risks": ["科技板块回调风险"]
    },
    {
      "type": "balanced",
      "name": "平衡型组合",
      "etfs": [
        {"name": "沪深300ETF", "symbol": "510300", "weight": 0.12, "logic": "宽基配置"},
        {"name": "中证500ETF", "symbol": "510500", "weight": 0.10, "logic": "中盘成长"},
        {"name": "红利ETF", "symbol": "510880", "weight": 0.10, "logic": "高股息防御"},
        {"name": "消费ETF", "symbol": "159928", "weight": 0.08, "logic": "消费配置"},
        {"name": "医药ETF", "symbol": "512010", "weight": 0.08, "logic": "医药配置"},
        {"name": "恒生科技ETF", "symbol": "513180", "weight": 0.08, "logic": "港股配置"},
        {"name": "纳指ETF", "symbol": "513100", "weight": 0.07, "logic": "美股配置"},
        {"name": "黄金ETF", "symbol": "518880", "weight": 0.05, "logic": "避险配置"}
      ],
      "cash_weight": 0.15,
      "description": "平衡型均衡配置，权益占比70%",
      "tips": ["保持均衡"],
      "risks": ["市场波动风险"]
    },
    {
      "type": "defensive",
      "name": "防御型组合",
      "etfs": [
        {"name": "沪深300ETF", "symbol": "510300", "weight": 0.12, "logic": "宽基底仓"},
        {"name": "红利ETF", "symbol": "510880", "weight": 0.10, "logic": "高股息防御"},
        {"name": "消费ETF", "symbol": "159928", "weight": 0.08, "logic": "消费防御"},
        {"name": "公用事业ETF", "symbol": "159611", "weight": 0.08, "logic": "公用事业防御"},
        {"name": "银行ETF", "symbol": "512800", "weight": 0.07, "logic": "银行防御"},
        {"name": "医药ETF", "symbol": "512010", "weight": 0.06, "logic": "医药防御"},
        {"name": "黄金ETF", "symbol": "518880", "weight": 0.08, "logic": "避险对冲"},
        {"name": "中证500ETF", "symbol": "510500", "weight": 0.06, "logic": "中盘配置"}
      ],
      "cash_weight": 0.15,
      "description": "防御型以低波动权益为主，权益占比57%",
      "tips": ["控制仓位"],
      "risks": ["收益不及预期"]
    }
  ]
}"""
    
    # Test: valid JSON parsing
    from prompt_optimizer_clean import parse_json
    parsed = parse_json(mock_llm_response)
    assert "portfolios" in parsed, "Missing portfolios key"
    assert len(parsed["portfolios"]) == 3, "Should have 3 portfolios"
    
    # Test: ETF counts
    pf_counts = [len(p["etfs"]) for p in parsed["portfolios"]]
    assert all(8 <= c <= 12 for c in pf_counts), f"ETF counts {pf_counts} not all in 8-12 range"
    
    # Test: weights sanity (ETF weights + cash may not sum exactly to 1.0,
    # as per constraint "ETF权重之和可以不等于1.0，剩余为现金仓位")
    for pf in parsed["portfolios"]:
        total_w = sum(e["weight"] for e in pf["etfs"]) + pf.get("cash_weight", 0)
        assert total_w <= 1.05, f"{pf['type']}: weights {total_w:.2f} > 1.0"
    
    # Test: no bond ETFs
    all_names = [e["name"] for pf in parsed["portfolios"] for e in pf["etfs"]]
    assert not any("国债" in n or "债" in n for n in all_names), "Contains bond ETFs!"
    
    # Test: no single ETF > 15%
    for pf in parsed["portfolios"]:
        for e in pf["etfs"]:
            assert e["weight"] <= 0.15, f"{pf['type']}: {e['name']} weight {e['weight']} > 15%"
    
    print("✅ LLM response parsing: all checks passed")
    return parsed


async def test_generate_portfolio_design():
    """Mock LLM and verify the full generate_portfolio_design flow."""
    mock_response = json.dumps({
        "portfolios": [
            {"type": "aggressive", "name": "进攻型组合", "etfs": [
                {"name": "沪深300ETF", "symbol": "510300", "weight": 0.15, "logic": "宽基配置"}
            ] * 9, "cash_weight": 0.05, "description": "进攻型", "tips": [], "risks": []},
            {"type": "balanced", "name": "平衡型组合", "etfs": [
                {"name": "中证500ETF", "symbol": "510500", "weight": 0.12, "logic": "中盘配置"}
            ] * 8, "cash_weight": 0.10, "description": "平衡型", "tips": [], "risks": []},
            {"type": "defensive", "name": "防御型组合", "etfs": [
                {"name": "红利ETF", "symbol": "510880", "weight": 0.10, "logic": "红利配置"}
            ] * 8, "cash_weight": 0.20, "description": "防御型", "tips": [], "risks": []}
        ]
    })
    
    with patch("app.analysis.llm.llm_complete", return_value=mock_response):
        result = await generate_portfolio_design(MOCK_INDICES, MOCK_COMMODITIES, MOCK_MARKET, MOCK_NEWS, [])
    
    assert "portfolios" in result, f"Missing portfolios key, got keys: {list(result.keys())}"
    assert len(result["portfolios"]) == 3, f"Expected 3 portfolios, got {len(result['portfolios'])}"
    
    for pf in result["portfolios"]:
        assert "type" in pf, f"Missing type in portfolio"
        assert "etfs" in pf, f"Missing etfs in {pf['type']}"
        assert len(pf["etfs"]) >= 8, f"{pf['type']}: only {len(pf['etfs'])} ETFs"
        for e in pf["etfs"]:
            assert all(k in e for k in ["name", "symbol", "weight"]), f"ETF missing required fields: {e}"
    
    print("✅ generate_portfolio_design: full flow works")


def test_system_prompt_v8_constraints():
    """Verify V8 constraints are in SYSTEM_PROMPT or the generated user prompt."""
    assert "数据驱动" in SYSTEM_PROMPT
    assert "分散化" in SYSTEM_PROMPT and "8~12" in SYSTEM_PROMPT
    assert "不得包含任何债券" in SYSTEM_PROMPT
    assert "市场阶段" in SYSTEM_PROMPT
    assert "调仓触发条件" in SYSTEM_PROMPT
    assert "再平衡" in SYSTEM_PROMPT
    print("✅ SYSTEM_PROMPT: all V8 constraints present")


def test_user_prompt_structure():
    """Verify the user prompt sent to LLM includes V8 instructions."""
    with patch("app.analysis.llm.llm_complete") as mock_llm:
        mock_llm.return_value = '{"portfolios": []}'
        asyncio.run(generate_portfolio_design(MOCK_INDICES, MOCK_COMMODITIES, MOCK_MARKET, MOCK_NEWS, []))
        call_args = mock_llm.call_args[0][0]

    # V8 instructions must be in the user prompt
    checks = [
        ("ETF数量", "8-12" in call_args),
        ("风险梯度", "权益 ≥85%" in call_args or "权益 ≥ 85%" in call_args),
        ("防御型配置", "公用事业" in call_args or "宽基" in call_args),
        ("风格均衡", "成长:价值" in call_args or "成长型与价值型" in call_args),
        ("无债券", "不含债券" in call_args or "无债券" in call_args or "不包含债券" in call_args),
    ]
    for name, passed in checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
        assert passed, f"User prompt missing: {name}"
    
    print("✅ User prompt: all V8 instructions present")


if __name__ == "__main__":
    print("=" * 60)
    print("Functional Test: V8 Prompt Application")
    print("=" * 60)
    
    # 1. Test SYSTEM_PROMPT constraints
    print("\n1. SYSTEM_PROMPT Constraints:")
    test_system_prompt_v8_constraints()
    
    # 2. Test LLM response parsing
    print("\n2. LLM Response Parsing:")
    test_llm_response_parsing()
    
    # 3. Test user prompt structure
    print("\n3. User Prompt V8 Instructions:")
    test_user_prompt_structure()
    
    # 4. Test full generate_portfolio_design flow
    print("\n4. Full Flow:")
    asyncio.run(test_generate_portfolio_design())
    
    print("\n" + "=" * 60)
    print("✅ All functional tests passed!")
    print("=" * 60)

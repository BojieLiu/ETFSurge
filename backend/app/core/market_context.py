"""
Market Context — 统一的市场上下文数据类和解析入口 (Phase 5.1).

提供 MarketContext 数据类和 resolve_market_context() 工厂函数。
所有接收 market 参数的端点通过此模块获取正确的市场配置。

用法:
    from app.core.market_context import resolve_market_context
    ctx = resolve_market_context("HK")
    regime = market_data_hub.get_market_regime(ctx.market)
"""

from __future__ import annotations

from dataclasses import dataclass

# ── 市场常量 ──────────────────────────────────────────────────

VALID_MARKETS = ("A", "HK", "US", "GLOBAL")

MARKET_INDEX_MAP: dict[str, set[str]] = {
    "A": {"000001", "399001", "399006", "000688", "000300"},
    "HK": {"^HSI", "^HSCE", "^HSTECH"},
    "US": {"^GSPC", "^IXIC", "^DJI"},
    "GLOBAL": set(),
}

MARKET_TITLE_MAP: dict[str, str] = {
    "A": "A股",
    "HK": "港股",
    "US": "美股",
    "GLOBAL": "全球市场",
}

MARKET_REGIME_INDEX_MAP: dict[str, str | None] = {
    "A": "000001",
    "HK": "^HSI",
    "US": "^GSPC",
    "GLOBAL": None,
}

# F17 R61: 东财行情 API 主机集中常量。
# 2026-08-01 实测（宿主机）：push2.eastmoney.com HTTP→502 错误网关、HTTPS→连接被关闭；
# push2delay.eastmoney.com HTTP→200 正常。P1.7「push2delay 回退 push2」前提不满足
# （P0.5 IPv4 优先已上线），故保留 push2delay 并集中管理，避免域名散落。
EM_PUSH_HOST = "push2delay.eastmoney.com"

# LLM 报告/分析中使用的"主要标的"符号集
MARKET_MAJOR_SYMBOLS: dict[str, set[str]] = {
    "A": {"000001", "399001", "399006", "000688", "000300", "510050", "510300", "510500", "159915"},
    "HK": {"HSI", "HSCEI", "00700", "09988", "02800"},
    "US": {"SPX", "IXIC", "SPY", "QQQ", "AAPL"},
    "GLOBAL": {"000001", "HSI", "SPX", "IXIC", "GC=F", "CL=F"},
}


@dataclass
class MarketContext:
    """统一市场上下文。包含市场相关的所有配置。

    Properties:
        market: "A" | "HK" | "US" | "global"
        title: 市场中文标题
        index_symbols: 该市场的指数代码集合
        major_symbols: LLM 分析用的主要标的代码集合
        regime_broad_index: 市态判断用的基准指数代码
        supports_sector_analysis: 是否有板块分析数据源
        supports_portfolio_design: 是否有 ETF 候选池
        supports_regime_detection: 是否支持市态判断
    """

    market: str  # "A" | "HK" | "US" | "global"

    @property
    def index_symbols(self) -> set[str]:
        return MARKET_INDEX_MAP.get(self.market, set())

    @property
    def major_symbols(self) -> set[str]:
        return MARKET_MAJOR_SYMBOLS.get(self.market, set())

    @property
    def title(self) -> str:
        return MARKET_TITLE_MAP.get(self.market, "未知市场")

    @property
    def regime_broad_index(self) -> str | None:
        """市态判断用的基准指数。global 无单一基准 → None。"""
        return MARKET_REGIME_INDEX_MAP.get(self.market)

    @property
    def supports_sector_analysis(self) -> bool:
        """板块分析仅 A 股有成熟数据源。"""
        return self.market == "A"

    @property
    def supports_portfolio_design(self) -> bool:
        """组合设计仅 A 股有完整候选池。"""
        return self.market == "A"

    @property
    def supports_regime_detection(self) -> bool:
        """市态判断仅 A/US 有可行数据。"""
        return self.market in ("A", "US")


def resolve_market_context(market: str | None) -> MarketContext:
    """统一的市场上下文解析入口。默认 A 股保持向后兼容。

    Args:
        market: "A" | "HK" | "US" | "global" 或 None

    Returns:
        MarketContext: 解析后的市场上下文
    """
    if not market:
        market = "A"
    market = market.strip().upper()
    if market not in VALID_MARKETS:
        market = "A"
    return MarketContext(market=market)

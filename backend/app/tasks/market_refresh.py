"""行情缓存预热（warmup 一次 + 请求驱动 TTL 回源）。

round35 §12.7 决策 B（2026-08-23）：APScheduler 定时推送链路已删除——调度器自
design-check-pipeline-redesign 危机期禁用一个月无人回切，请求驱动（REST TTL 轮询）
被实证接受；恢复只会复活「空闲空转打免费源」的原始问题（封禁风险）。

本模块现仅保留 warmup 预热入口：调 hub.get_portfolio_realtime() 填充行情缓存，
使启动后首个请求直接命中。不再向 WS 广播 ``{type:'realtime'}``——前端消费分支
已同批删除（market.js），portfolio 频道的 portfolio_changed 广播独立存活于
routers/portfolio.py，与本决策无关。
"""

from ..core.logging import get_logger
from ..services.market_data_hub import market_data_hub

logger = get_logger(__name__)


async def refresh_market_cache(phase: str = "all") -> None:
    """预热组合行情缓存（无 WS 推送；失败由调用方按预热语义处理）。

    round49 A4-C: phase 参数支持两阶段预热, 治本 warmup_market_cache 10.57s
    根因 (off_exchange 串行 fetch_fund_nav 拉长整体). 设计:
      - phase="all"  (默认, 兼容旧调用方): 走完整 get_portfolio_realtime
      - phase="fast" (A 股+指数, 5s 内返回, 写 cache): 跑快源子集
      - phase="slow" (off_exchange 场外 fetch_fund_nav, 25s 预算, 写 cache): 跑慢源子集
    快慢源两次写同一 cache key, 后写覆盖前写 (竞态可接受, 15s TTL 自动续期).

    warmup 调用方: _do_market_warmup 先 await phase="fast" (5s) 拿快源, 立刻
    background spawn phase="slow" 补慢源. 用户首击命中 fast cache, 后台续
    补 slow (完成后下次首击命中完整 cache).
    """
    try:
        await market_data_hub.get_portfolio_realtime(phase=phase)
    except Exception:
        logger.exception("预热行情缓存失败 (phase=%s): hub exception", phase)

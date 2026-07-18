"""WebSocket design report composer"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..analysis.llm import generate_design_report

logger = logging.getLogger(__name__)

# In-memory connection manager for design report sessions
class DesignReportManager:
    def __init__(self):
        self._sessions: dict[str, set] = {}  # session_id -> set of ws references
        self._running: dict[str, bool] = {}   # session_id -> is LLM already running?

    def register(self, session_id: str, websocket) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = set()
        self._sessions[session_id].add(websocket)

    def unregister(self, session_id: str, websocket) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].discard(websocket)
            if not self._sessions[session_id]:
                del self._sessions[session_id]

    async def broadcast(self, session_id: str, message: dict) -> None:
        if session_id not in self._sessions:
            return
        payload = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in self._sessions[session_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister(session_id, ws)

    def is_running(self, session_id: str) -> bool:
        return self._running.get(session_id, False)

    def mark_running(self, session_id: str, val: bool) -> None:
        self._running[session_id] = val


report_manager = DesignReportManager()


def _validate_report_consistency(report_text: str, strategies: list[dict]) -> str:
    """校验 LLM 报告中的 ETF 代码是否与引擎策略数据一致。
    如 LLM 引入了引擎方案以外的标的，追加修正脚注。
    如 LLM 遗漏了三个方案中的某个，追加提醒段落。"""
    import re

    # 提取引擎策略中的所有 ETF 代码
    engine_symbols: set[str] = set()
    for s in strategies:
        for a in s.get("allocations") or s.get("etfs") or []:
            sym = a.get("symbol", "")
            if sym and sym != "CASH":
                engine_symbols.add(sym)

    # 提取报告中所有 ETF 代码（6 位纯数字）
    report_symbols: set[str] = set(re.findall(r"\b(\d{6})\b", report_text))

    # 差集：LLM 写了哪些引擎没有的标的
    extra_symbols = report_symbols - engine_symbols
    if extra_symbols:
        extra_note = (
            "\n\n> **⚠️ 一致性说明**：以下代码在报告中出现但不在引擎方案中："
            + ", ".join(sorted(extra_symbols))
            + "。以上分析仅供参考，实际配置以方案卡片中的 ETF 标的和权重为准。"
        )
        report_text += extra_note

    # 检查是否覆盖了三种方案
    plan_names = [s.get("label", "") or s.get("style", "") for s in strategies]
    missing = [n for n in plan_names if n and n not in report_text]
    if missing:
        miss_note = (
            "\n\n> **📋 方案说明**：系统共生成 "
            + "、".join(plan_names)
            + " 三个方案，报告未完整展开的方案请参考「方案卡片」Tab 查看完整明细。"
        )
        report_text += miss_note

    return report_text


async def compose_and_push_report(
    session_id: str,
    strategies: list[dict],
    market_sentiment: dict | None = None,
    benchmark_stocks: list[dict] | None = None,
    market_context: dict | None = None,
    design_id: int | None = None,  # 传 design_id 时，报告完成后写回数据库
) -> None:
    """生成 LLM 报告并通过 WS 推送。

    P1 增强：新增 market_context 参数，透传完整市场上下文（含 index_realtime /
    market_regime / macro_regime / sector_momentum）给 LLM 报告，取代仅用
    market_sentiment + benchmark_stocks 的狭窄输入。旧调用（仅传前两个字段）
    仍向后兼容。

    流程:
      1. 推送 status=generating, progress=10
      2. 调用 LLM generate_design_report
      3. 推送 chunks (status=streaming)
      4. 推送 complete (status=complete) 或 error
    """
    if report_manager.is_running(session_id):
        logger.info("[design_report] session %s already running, skipping", session_id)
        return

    report_manager.mark_running(session_id, True)
    try:
        # 推送进度: 开始
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "generating",
            "progress": 10,
            "stage": "正在分析市场环境...",
        })

        # 调用 LLM（P1: 透传完整 market_context）
        report_text = await generate_design_report(
            strategies=strategies,
            market_sentiment=market_sentiment,
            benchmark_stocks=benchmark_stocks,
            market_context=market_context,
        )

        if not report_text:
            logger.warning("[design_report] LLM returned empty, generating fallback summary")
            fallback_parts = [
                "# ETF 组合设计方案（数据摘要）\n",
                f"市场状态：{market_context.get('market_regime', '—')}\n",
            ]
            for s in strategies:
                label = s.get("label", "")
                lb = s.get("layer_budget", {})
                fallback_parts.append(f"\n## {label}\n")
                fallback_parts.append(f"核心 {lb.get('core',0)*100:.0f}% · 卫星 {lb.get('satellite',0)*100:.0f}% · 防御 {lb.get('defense',0)*100:.0f}%\n\n")
                for e in (s.get("allocations") or s.get("etfs") or []):
                    if e.get("symbol") == "CASH": continue
                    w = (e.get("weight") or e.get("target_weight") or 0) * 100
                    fallback_parts.append(f"- {e.get('name','')} ({e.get('symbol')}) {w:.0f}% — {e.get('selection_rationale','')[:80]}\n")
            report_text = "".join(fallback_parts)
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "complete",
                "report_text": report_text,
            })
            # 写库
            if design_id is not None:
                try:
                    from ..database import async_session
                    from ..models.portfolio_design import PortfolioDesign
                    async with async_session() as db:
                        d = await db.get(PortfolioDesign, design_id)
                        if d:
                            d.design_text = report_text
                            await db.commit()
                except Exception as pe:
                    logger.error("[design_report] fallback persist error: %s", pe)
            return

        # 推送进度: 撰写完成
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "generating",
            "progress": 60,
            "stage": "报告撰写完成，正在格式化...",
        })

        # 按段落推送 chunks（模拟流式）
        paragraphs = report_text.split("\n\n")
        for i, para in enumerate(paragraphs):
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "streaming",
                "chunk": para + "\n\n",
            })
            progress = 60 + int(40 * (i + 1) / max(len(paragraphs), 1))
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "generating",
                "progress": min(progress, 95),
                "stage": "传输中...",
            })
            await asyncio.sleep(0.05)  # 模拟流式延时

        # 推送完成
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "complete",
            "report_text": report_text,
        })

        # 持久化：将报告文本写入数据库（如果传了 design_id）
        if design_id is not None and report_text:
            try:
                from ..database import async_session
                from ..models.portfolio_design import PortfolioDesign
                async with async_session() as db:
                    design = await db.get(PortfolioDesign, design_id)
                    if design:
                        design.design_text = report_text
                        await db.commit()
                        logger.info("[design_report] persisted design_text for design %s", design_id)
                    else:
                        logger.warning("[design_report] design %s not found for persist", design_id)
            except Exception as persist_e:
                logger.error("[design_report] failed to persist design_text: %s", persist_e)

        # 一致性校验：对比 LLM 报告的 ETF 代码与引擎策略数据
        try:
            report_text = _validate_report_consistency(report_text, strategies)
        except Exception as ve:
            logger.warning("[design_report] consistency check failed (non-blocking): %s", ve)

    except Exception as e:
        logger.error("[design_report] error for session %s: %s", session_id, e)
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "error",
            "message": f"报告生成异常: {e}",
        })
    finally:
        report_manager.mark_running(session_id, False)

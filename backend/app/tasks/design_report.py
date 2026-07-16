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


async def compose_and_push_report(
    session_id: str,
    strategies: list[dict],
    market_sentiment: dict | None = None,
    benchmark_stocks: list[dict] | None = None,
) -> None:
    """生成 LLM 报告并通过 WS 推送。

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

        # 调用 LLM
        report_text = await generate_design_report(
            strategies=strategies,
            market_sentiment=market_sentiment,
            benchmark_stocks=benchmark_stocks,
        )

        if not report_text:
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "error",
                "message": "报告生成失败",
            })
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

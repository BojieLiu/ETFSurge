import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, channel: str = "market"):
        await websocket.accept()
        async with self._lock:
            self.active_connections.setdefault(channel, []).append(websocket)

    async def disconnect(self, websocket: WebSocket, channel: str = "market"):
        async with self._lock:
            try:
                self.active_connections.get(channel, []).remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, channel: str, message: dict):
        # 锁内快照，锁外逐个发送以避免持有锁期间 send_text 阻塞
        async with self._lock:
            targets = list(self.active_connections.get(channel, []))
        for conn in targets:
            try:
                await conn.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                pass


manager = ConnectionManager()


@router.websocket("/api/v1/ws/market/{symbol}")
async def market_ws(websocket: WebSocket, symbol: str):
    await manager.connect(websocket, f"market:{symbol}")
    try:
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
    except WebSocketDisconnect:
        await manager.disconnect(websocket, f"market:{symbol}")
    except Exception:
        await manager.disconnect(websocket, f"market:{symbol}")


@router.websocket("/api/v1/ws/news")
async def news_ws(websocket: WebSocket):
    await manager.connect(websocket, "news")
    try:
        # 订阅即推快照：立即推送当前最新头条，避免广播间隙空等
        try:
            from ..fetchers.news_fetcher import fetch_news_headlines
            headlines = await asyncio.to_thread(fetch_news_headlines)
            for item in (headlines or [])[:30]:
                await websocket.send_text(json.dumps({"type": "news", "data": item}, ensure_ascii=False))
        except Exception:
            pass
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
    except WebSocketDisconnect:
        await manager.disconnect(websocket, "news")
    except Exception:
        await manager.disconnect(websocket, "news")


@router.websocket("/api/v1/ws/portfolio")
async def portfolio_ws(websocket: WebSocket):
    await manager.connect(websocket, "portfolio")
    try:
        await websocket.send_text(json.dumps({"type": "hello", "data": "connected"}, ensure_ascii=False))
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
    except WebSocketDisconnect:
        await manager.disconnect(websocket, "portfolio")
    except Exception:
        await manager.disconnect(websocket, "portfolio")


@router.websocket("/api/v1/ws/design-report/{session_id}")
async def design_report_ws(websocket: WebSocket, session_id: str):
    """被动监听 WebSocket: 前端连接后，后端通过 report_manager 推送 LLM 报告。"""
    from ..tasks.design_report import report_manager

    await websocket.accept()
    report_manager.register(session_id, websocket)

    try:
        # 保持连接，等待后端推送 LLM 报告（由 REST API 后台任务触发）
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("[design_report_ws] error: %s", e)
    finally:
        report_manager.unregister(session_id, websocket)

@router.websocket("/api/v1/ws/task-notifications")
async def task_notifications_ws(websocket: WebSocket):
    """任务状态变更通知 WebSocket。"""
    from ..tasks.task_manager import notify_manager

    await websocket.accept()
    notify_manager.register(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in ("ping", "heartbeat"):
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        notify_manager.unregister(websocket)

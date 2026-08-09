import asyncio
import json
import logging
import time
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = 60  # S3-C: 60s cleanup interval
        self._last_cleanup = time.time()

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

    async def _cleanup_stale(self) -> None:
        """S3-C: 扫描无效连接并清理。"""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        async with self._lock:
            for channel, conns in list(self.active_connections.items()):
                alive = []
                for ws in conns:
                    try:
                        state = getattr(ws, 'client_state', None)
                        name = state.name if state else "CONNECTED"
                        if name == "CONNECTED":
                            alive.append(ws)
                        else:
                            logger.debug("[ws] cleanup disconnected client from %s", channel)
                    except Exception:
                        alive.append(ws)
                if len(alive) != len(conns):
                    self.active_connections[channel] = alive
                    logger.info("[ws] cleanup %s: removed %d stale conns",
                                channel, len(conns) - len(alive))

    async def broadcast(self, channel: str, message: dict):
        """广播消息，每个客户端有 5s 超时保护（S3-B）。
        同时每隔 60s 扫描无效连接并清理（S3-C）。"""
        await self._cleanup_stale()
        async with self._lock:
            targets = list(self.active_connections.get(channel, []))
        payload = json.dumps(message, ensure_ascii=False)
        for conn in targets:
            try:
                await asyncio.wait_for(conn.send_text(payload), timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                logger.debug("[ws] broadcast timeout/error on %s, disconnecting", channel)
                await self.disconnect(conn, channel)


manager = ConnectionManager()


async def _ws_loop(websocket: WebSocket) -> None:
    """WS 保活循环样板（round11 P1-4）：receive_text + ping/heartbeat → pong。

    5 个端点此前各自复制该循环；抽取后端点只需处理注册/注销差异。
    连接断开时 receive_text 抛 WebSocketDisconnect/异常，由调用方捕获处理。
    """
    while True:
        data = await websocket.receive_text()
        if data.strip().lower() in ("ping", "heartbeat"):
            await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))


@router.websocket("/api/v1/ws/market/{symbol}")
async def market_ws(websocket: WebSocket, symbol: str):
    await manager.connect(websocket, f"market:{symbol}")
    try:
        await _ws_loop(websocket)
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
            from ..services.market_data_hub import market_data_hub
            headlines = await asyncio.to_thread(market_data_hub.get_news_headlines)
            for item in (headlines or [])[:30]:
                await websocket.send_text(json.dumps({"type": "news", "data": item}, ensure_ascii=False))
        except Exception:
            pass
        await _ws_loop(websocket)
    except WebSocketDisconnect:
        await manager.disconnect(websocket, "news")
    except Exception:
        await manager.disconnect(websocket, "news")


@router.websocket("/api/v1/ws/portfolio")
async def portfolio_ws(websocket: WebSocket):
    await manager.connect(websocket, "portfolio")
    try:
        await websocket.send_text(json.dumps({"type": "hello", "data": "connected"}, ensure_ascii=False))
        await _ws_loop(websocket)
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
        await _ws_loop(websocket)
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
        await _ws_loop(websocket)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        notify_manager.unregister(websocket)

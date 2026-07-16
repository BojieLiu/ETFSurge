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
    """设计报告 LLM 结果推送 WebSocket。"""
    from ..tasks.design_report import report_manager, compose_and_push_report
    from ..services.strategy_design import generate_full_design

    await websocket.accept()
    report_manager.register(session_id, websocket)

    try:
        # 等待前端发送方案请求（携带 capital/constraints 参数）
        msg = await websocket.receive_text()
        params = json.loads(msg)

        # 生成方案
        await report_manager.broadcast(session_id, {
            "type": "design_report", "session_id": session_id,
            "status": "generating", "progress": 5, "stage": "正在生成组合方案..."
        })

        design_result = await generate_full_design(
            capital=params.get("capital", 500000),
            constraints=params.get("constraints"),
        )

        strategies = design_result.get("strategies", [])
        market_context = design_result.get("market_context", {})
        market_sentiment = market_context.get("market_sentiment", {})
        benchmark_stocks = market_context.get("benchmark_stocks", [])

        # 启动后台 LLM 报告生成 (异步，不阻塞)
        asyncio.create_task(compose_and_push_report(
            session_id=session_id,
            strategies=strategies,
            market_sentiment=market_sentiment,
            benchmark_stocks=benchmark_stocks,
        ))

        # 先返回方案数据（卡片展示用）
        await report_manager.broadcast(session_id, {
            "type": "design_result",
            "session_id": session_id,
            "strategies": strategies,
        })

        # 保持连接，等待 LLM 报告推送完成
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

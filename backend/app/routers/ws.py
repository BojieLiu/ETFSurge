import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, channel: str = "market"):
        await websocket.accept()
        if channel not in self.active_connections:
            self.active_connections[channel] = []
        self.active_connections[channel].append(websocket)

    def disconnect(self, websocket: WebSocket, channel: str = "market"):
        if channel in self.active_connections:
            self.active_connections[channel].remove(websocket)

    async def broadcast(self, channel: str, message: dict):
        if channel not in self.active_connections:
            return
        for conn in self.active_connections[channel]:
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
    except WebSocketDisconnect:
        manager.disconnect(websocket, f"market:{symbol}")


@router.websocket("/api/v1/ws/news")
async def news_ws(websocket: WebSocket):
    await manager.connect(websocket, "news")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, "news")


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
        manager.disconnect(websocket, "portfolio")
    except Exception:
        manager.disconnect(websocket, "portfolio")

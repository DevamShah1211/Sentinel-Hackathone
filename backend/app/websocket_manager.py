"""WebSocket connection manager for live alert broadcasting."""
from fastapi import WebSocket
import json
import logging

logger = logging.getLogger("sentinel.ws")


class WebSocketManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WS client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"WS client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send a message to every connected client."""
        text = json.dumps(message, default=str)
        dead = []
        for ws in self.active_connections:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_alert(self, alert_data: dict):
        await self.broadcast({"type": "alert", "data": alert_data})


ws_manager = WebSocketManager()

"""WebSocket connection manager for real-time progress updates (not the `websockets` PyPI package)."""

import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manage WebSocket connections for job progress updates."""

    def __init__(self) -> None:
        """Initialize the connection manager."""
        # Map job_id to set of connected WebSockets
        self._connections: Dict[str, Set[WebSocket]] = {}
        # Map WebSocket to job_id for reverse lookup
        self._socket_jobs: Dict[WebSocket, str] = {}

    async def connect(self, websocket: WebSocket, job_id: str) -> None:
        """Accept a new WebSocket connection for a job."""
        await websocket.accept()

        if job_id not in self._connections:
            self._connections[job_id] = set()

        self._connections[job_id].add(websocket)
        self._socket_jobs[websocket] = job_id

        logger.info(
            f"WebSocket connected for job {job_id}. Total connections: {len(self._connections[job_id])}"
        )

    def disconnect(self, websocket: WebSocket, job_id: str) -> None:
        """Remove a WebSocket connection."""
        if job_id in self._connections:
            self._connections[job_id].discard(websocket)

            if not self._connections[job_id]:
                del self._connections[job_id]

        self._socket_jobs.pop(websocket, None)

        logger.info(f"WebSocket disconnected from job {job_id}")

    async def send_progress(self, job_id: str, progress: int, message: str = "") -> None:
        """Send progress update to all connections for a job."""
        if job_id not in self._connections:
            return

        data = {
            "type": "progress",
            "job_id": job_id,
            "progress": progress,
            "message": message,
        }

        # Send to all connected clients
        disconnected = []
        for websocket in self._connections[job_id]:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)

        # Clean up disconnected sockets
        for websocket in disconnected:
            self.disconnect(websocket, job_id)

    async def send_log(self, job_id: str, level: str, message: str) -> None:
        """Send log message to all connections for a job."""
        if job_id not in self._connections:
            return

        data = {
            "type": "log",
            "job_id": job_id,
            "log": {
                "level": level,
                "message": message,
                "timestamp": self._get_timestamp(),
            },
        }

        disconnected = []
        for websocket in self._connections[job_id]:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket, job_id)

    async def send_status(self, job_id: str, status: str, details: dict = None) -> None:
        """Send status update to all connections for a job."""
        if job_id not in self._connections:
            return

        data = {
            "type": "status",
            "job_id": job_id,
            "status": status,
        }

        if details:
            data["details"] = details

        disconnected = []
        for websocket in self._connections[job_id]:
            try:
                await websocket.send_json(data)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket, job_id)

    async def broadcast(self, job_id: str, message: dict) -> None:
        """Broadcast a message to all connections for a job."""
        if job_id not in self._connections:
            return

        disconnected = []
        for websocket in self._connections[job_id]:
            try:
                await websocket.send_json(message)
            except Exception:
                disconnected.append(websocket)

        for websocket in disconnected:
            self.disconnect(websocket, job_id)

    def get_connection_count(self, job_id: str) -> int:
        """Get the number of active connections for a job."""
        return len(self._connections.get(job_id, set()))

    @staticmethod
    def _get_timestamp() -> str:
        """Get current ISO timestamp."""
        from datetime import datetime

        return datetime.utcnow().isoformat()

"""Shared state for the API server.

This module holds shared state that can be accessed by all route modules
without causing circular imports.
"""

from typing import Dict, Any
from .connection_manager import ConnectionManager

# In-memory job store (in production, use Redis or similar)
jobs: Dict[str, Dict[str, Any]] = {}

# WebSocket connection manager
manager = ConnectionManager()


def get_job_store() -> Dict[str, Dict[str, Any]]:
    """Get the job store."""
    return jobs


def get_websocket_manager() -> ConnectionManager:
    """Get the WebSocket manager."""
    return manager

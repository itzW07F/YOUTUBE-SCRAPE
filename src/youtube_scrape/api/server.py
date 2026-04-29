#!/usr/bin/env python3
"""
FastAPI server for YouTube Scrape GUI.

This module provides the HTTP API and WebSocket endpoints for the Electron frontend
to interact with the scraping services.
"""

import argparse
import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Add parent directories to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.routes import scrape, dl as download, config, batch, metadata_refresh
from api.state import get_job_store, get_websocket_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Handle application startup and shutdown."""
    # Startup
    logger.info("Starting YouTube Scrape API server...")
    
    # Ensure output directory exists
    output_dir = os.environ.get("OUTPUT_DIR", "output")
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"Server ready - output directory: {output_dir}")
    
    yield
    
    # Shutdown
    logger.info("Shutting down server...")


# Create FastAPI app
app = FastAPI(
    title="YouTube Scrape API",
    description="API for YouTube Scraper Electron GUI",
    version="1.0.0",
    lifespan=lifespan,
)

# Add CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to Electron origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(scrape.router, prefix="/scrape", tags=["scrape"])
app.include_router(download.router, prefix="/download", tags=["download"])
app.include_router(config.router, prefix="/config", tags=["config"])
app.include_router(batch.router, prefix="/batch", tags=["batch"])
app.include_router(metadata_refresh.router, prefix="/metadata", tags=["metadata"])


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Health check endpoint."""
    job_store = get_job_store()
    return {
        "status": "healthy",
        "version": "1.0.0",
        "jobs_active": len([j for j in job_store.values() if j.get("status") == "running"]),
        "jobs_total": len(job_store),
    }


@app.get("/jobs/{job_id}")
async def get_job_status(job_id: str) -> JSONResponse:
    """Get status of a specific job."""
    job_store = get_job_store()
    if job_id not in job_store:
        return JSONResponse(
            status_code=404,
            content={"error": "Job not found"}
        )
    
    return JSONResponse(content=job_store[job_id])


@app.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> JSONResponse:
    """Cancel a running job."""
    job_store = get_job_store()
    ws = get_websocket_manager()
    if job_id not in job_store:
        return JSONResponse(
            status_code=404,
            content={"error": "Job not found"}
        )
    
    job = job_store[job_id]
    if job["status"] != "running":
        return JSONResponse(
            status_code=400,
            content={"error": f"Job is not running (status: {job['status']})"}
        )
    
    job["status"] = "cancelled"
    job["cancel_requested"] = True
    
    # Notify via WebSocket
    await ws.broadcast(job_id, {
        "type": "cancelled",
        "job_id": job_id,
        "message": "Job cancelled by user"
    })
    
    return JSONResponse(content={"status": "cancelled", "job_id": job_id})


@app.websocket("/ws/progress/{job_id}")
async def progress_websocket(websocket: WebSocket, job_id: str) -> None:
    """WebSocket endpoint for real-time job progress."""
    ws = get_websocket_manager()
    job_store = get_job_store()
    await ws.connect(websocket, job_id)
    
    try:
        # Send initial status
        if job_id in job_store:
            await websocket.send_json({
                "type": "status",
                "job_id": job_id,
                "data": job_store[job_id]
            })
        
        # Keep connection alive and handle client messages
        while True:
            try:
                # Wait for messages (ping/pong or commands)
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                
                # Echo back for ping/pong
                if data == "ping":
                    await websocket.send_text("pong")
                    
            except asyncio.TimeoutError:
                # Send heartbeat
                await websocket.send_json({"type": "heartbeat"})
                
    except WebSocketDisconnect:
        ws.disconnect(websocket, job_id)
    except Exception as e:
        logger.error(f"WebSocket error for job {job_id}: {e}")
        ws.disconnect(websocket, job_id)


def main() -> None:
    """Run the API server."""
    parser = argparse.ArgumentParser(description="YouTube Scrape API Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    
    args = parser.parse_args()
    
    # Use environment variables if provided (from Electron)
    host = os.environ.get("API_HOST", args.host)
    port = int(os.environ.get("API_PORT", args.port))
    
    import uvicorn
    
    uvicorn.run(
        "api.server:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()

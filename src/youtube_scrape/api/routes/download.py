"""Download endpoints for the API."""

import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from api.state import get_job_store, get_websocket_manager

logger = logging.getLogger(__name__)
router = APIRouter()


class DownloadRequest(BaseModel):
    url: str
    format: str = "mp4"
    quality: str = "best"


class DownloadResponse(BaseModel):
    job_id: str
    status: str
    output_dir: str
    message: str


@router.post("/video", response_model=DownloadResponse)
async def download_video(
    request: DownloadRequest,
    background_tasks: BackgroundTasks
) -> DownloadResponse:
    jobs = get_job_store()
    job_id = str(uuid.uuid4())[:8]
    
    from api.routes.scrape import extract_video_id
    video_id = extract_video_id(request.url)
    output_dir = os.path.abspath(os.path.join("output", video_id))
    
    jobs[job_id] = {
        "id": job_id,
        "url": request.url,
        "status": "pending",
        "progress": 0,
        "type": "download",
        "output_dir": output_dir,
        "options": request.model_dump(),
        "created_at": datetime.utcnow().isoformat(),
        "logs": [],
    }
    
    return DownloadResponse(
        job_id=job_id,
        status="started",
        output_dir=output_dir,
        message="Download job started"
    )


@router.get("/formats")
async def get_available_formats(url: str) -> List[Dict[str, Any]]:
    return [
        {"format_id": "best", "ext": "mp4", "quality": "best"},
        {"format_id": "22", "ext": "mp4", "quality": "720p"},
    ]

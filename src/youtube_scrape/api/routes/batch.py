"""Batch processing endpoints for the API."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, HTTPException, Form
from pydantic import BaseModel, Field

from api.state import get_job_store, get_websocket_manager
from api.routes.scrape import ScrapeVideoRequest, extract_video_id

logger = logging.getLogger(__name__)

router = APIRouter()


class BatchRequest(BaseModel):
    """Batch scraping request."""
    urls: List[str] = Field(..., description="List of YouTube URLs to scrape")
    options: ScrapeVideoRequest = Field(default_factory=lambda: ScrapeVideoRequest())


class BatchResponse(BaseModel):
    """Batch scraping response."""
    batch_id: str
    job_count: int
    status: str
    message: str


class BatchJob(BaseModel):
    """Individual job in a batch."""
    job_id: str
    url: str
    status: str
    progress: int


class BatchStatus(BaseModel):
    """Status of a batch job."""
    batch_id: str
    total_jobs: int
    completed_jobs: int
    failed_jobs: int
    running_jobs: int
    pending_jobs: int
    status: str  # pending, running, completed, failed
    jobs: List[BatchJob]
    started_at: str
    completed_at: Optional[str]


async def run_batch(batch_id: str, urls: List[str], options: ScrapeVideoRequest) -> None:
    """Run a batch of scrape jobs."""
    jobs = get_job_store()
    manager = get_websocket_manager()
    
    batch_info = jobs.get(batch_id, {})
    job_ids: List[str] = []
    
    # Create individual jobs
    for url in urls:
        job_id = str(uuid.uuid4())[:8]
        video_id = extract_video_id(url)
        
        jobs[job_id] = {
            "id": job_id,
            "url": url,
            "status": "pending",
            "progress": 0,
            "type": "all",
            "output_dir": f"output/{video_id}",
            "options": options.model_dump(),
            "created_at": datetime.utcnow().isoformat(),
            "logs": [],
            "batch_id": batch_id,
        }
        
        job_ids.append(job_id)
    
    # Update batch info
    batch_info["job_ids"] = job_ids
    batch_info["total_jobs"] = len(job_ids)
    batch_info["pending_jobs"] = len(job_ids)
    batch_info["status"] = "running"
    jobs[batch_id] = batch_info
    
    await manager.send_status(batch_id, "running", {
        "message": f"Started batch with {len(job_ids)} jobs",
        "total_jobs": len(job_ids),
    })
    
    # Process jobs sequentially (or with limited concurrency)
    max_concurrent = 2
    active_jobs = 0
    
    for i, job_id in enumerate(job_ids):
        job = jobs[job_id]
        
        # Wait if too many concurrent jobs
        while active_jobs >= max_concurrent:
            await asyncio.sleep(0.5)
            active_jobs = sum(
                1 for jid in job_ids
                if jobs.get(jid, {}).get("status") == "running"
            )
        
        # Start the job
        job["status"] = "running"
        batch_info["pending_jobs"] -= 1
        batch_info["running_jobs"] = active_jobs + 1
        
        # Run the job
        try:
            # Simulate job execution (replace with actual service call)
            import asyncio
            await manager.send_progress(job_id, 0, "Starting...")
            await asyncio.sleep(2)  # Simulate work
            
            job["status"] = "completed"
            job["progress"] = 100
            job["completed_at"] = datetime.utcnow().isoformat()
            
            batch_info["completed_jobs"] = batch_info.get("completed_jobs", 0) + 1
            batch_info["running_jobs"] -= 1
            
            await manager.send_status(job_id, "completed")
            
        except Exception as e:
            logger.error(f"Batch job {job_id} failed: {e}")
            job["status"] = "failed"
            job["error"] = str(e)
            batch_info["failed_jobs"] = batch_info.get("failed_jobs", 0) + 1
            batch_info["running_jobs"] -= 1
            
            await manager.send_status(job_id, "failed", {"error": str(e)})
        
        # Send batch progress update
        await manager.send_progress(
            batch_id,
            int((i + 1) / len(job_ids) * 100),
            f"Processed {i + 1} of {len(job_ids)} jobs"
        )
    
    # Mark batch as completed
    batch_info["status"] = "completed"
    batch_info["completed_at"] = datetime.utcnow().isoformat()
    batch_info["running_jobs"] = 0
    
    await manager.send_status(batch_id, "completed", {
        "message": f"Batch completed: {batch_info.get('completed_jobs', 0)} succeeded, {batch_info.get('failed_jobs', 0)} failed",
    })


@router.post("/start", response_model=BatchResponse)
async def start_batch(
    request: BatchRequest,
    background_tasks: BackgroundTasks
) -> BatchResponse:
    """Start a batch scraping job."""
    jobs = get_job_store()
    
    batch_id = f"batch_{str(uuid.uuid4())[:8]}"
    
    # Validate URLs
    valid_urls = []
    invalid_urls = []
    
    for url in request.urls:
        if url.strip():
            # Basic URL validation
            if "youtube.com" in url or "youtu.be" in url:
                valid_urls.append(url.strip())
            else:
                invalid_urls.append(url.strip())
    
    if not valid_urls:
        raise HTTPException(status_code=400, detail="No valid YouTube URLs provided")
    
    # Create batch entry
    jobs[batch_id] = {
        "id": batch_id,
        "type": "batch",
        "status": "pending",
        "urls": valid_urls,
        "total_jobs": len(valid_urls),
        "completed_jobs": 0,
        "failed_jobs": 0,
        "running_jobs": 0,
        "pending_jobs": len(valid_urls),
        "started_at": datetime.utcnow().isoformat(),
        "options": request.options.model_dump(),
    }
    
    # Start batch in background
    background_tasks.add_task(run_batch, batch_id, valid_urls, request.options)
    
    message = f"Batch started with {len(valid_urls)} jobs"
    if invalid_urls:
        message += f" ({len(invalid_urls)} invalid URLs skipped)"
    
    return BatchResponse(
        batch_id=batch_id,
        job_count=len(valid_urls),
        status="started",
        message=message
    )


@router.post("/upload")
async def upload_batch_file(
    file: UploadFile = File(...)
) -> Dict[str, Any]:
    """Upload a file with URLs for batch processing."""
    try:
        content = await file.read()
        text = content.decode('utf-8')
        
        # Parse URLs from file
        urls = [
            line.strip()
            for line in text.split('\n')
            if line.strip() and not line.startswith('#')
        ]
        
        # Create options
        options = ScrapeVideoRequest(
            url=urls[0] if urls else "",  # Dummy URL for base options
            include_video=include_video,
            include_comments=include_comments,
            max_comments=max_comments,
        )
        
        # Start batch (reuse the start_batch logic)
        jobs = get_job_store()
        batch_id = f"batch_{str(uuid.uuid4())[:8]}"
        
        valid_urls = [u for u in urls if "youtube.com" in u or "youtu.be" in u]
        
        jobs[batch_id] = {
            "id": batch_id,
            "type": "batch",
            "status": "pending",
            "urls": valid_urls,
            "total_jobs": len(valid_urls),
            "completed_jobs": 0,
            "failed_jobs": 0,
            "running_jobs": 0,
            "pending_jobs": len(valid_urls),
            "started_at": datetime.utcnow().isoformat(),
            "options": options.model_dump(),
        }
        
        background_tasks.add_task(run_batch, batch_id, valid_urls, options)
        
        return {
            "batch_id": batch_id,
            "job_count": len(valid_urls),
            "status": "started",
            "filename": file.filename,
        }
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to process file: {e}")


@router.get("/status/{batch_id}", response_model=BatchStatus)
async def get_batch_status(batch_id: str) -> BatchStatus:
    """Get status of a batch job."""
    jobs = get_job_store()
    
    if batch_id not in jobs:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    batch = jobs[batch_id]
    
    # Get individual job statuses
    job_statuses: List[BatchJob] = []
    for job_id in batch.get("job_ids", []):
        job = jobs.get(job_id, {})
        job_statuses.append(BatchJob(
            job_id=job_id,
            url=job.get("url", ""),
            status=job.get("status", "unknown"),
            progress=job.get("progress", 0),
        ))
    
    return BatchStatus(
        batch_id=batch_id,
        total_jobs=batch.get("total_jobs", 0),
        completed_jobs=batch.get("completed_jobs", 0),
        failed_jobs=batch.get("failed_jobs", 0),
        running_jobs=batch.get("running_jobs", 0),
        pending_jobs=batch.get("pending_jobs", 0),
        status=batch.get("status", "unknown"),
        jobs=job_statuses,
        started_at=batch.get("started_at", ""),
        completed_at=batch.get("completed_at"),
    )


@router.post("/cancel/{batch_id}")
async def cancel_batch(batch_id: str) -> Dict[str, Any]:
    """Cancel a running batch job."""
    jobs = get_job_store()
    manager = get_websocket_manager()
    
    if batch_id not in jobs:
        raise HTTPException(status_code=404, detail="Batch not found")
    
    batch = jobs[batch_id]
    
    if batch.get("status") not in ["pending", "running"]:
        raise HTTPException(status_code=400, detail=f"Batch is {batch['status']}")
    
    # Cancel all pending/running jobs in the batch
    cancelled_count = 0
    for job_id in batch.get("job_ids", []):
        job = jobs.get(job_id, {})
        if job.get("status") in ["pending", "running"]:
            job["status"] = "cancelled"
            job["cancel_requested"] = True
            cancelled_count += 1
    
    batch["status"] = "cancelled"
    batch["cancelled_at"] = datetime.utcnow().isoformat()
    
    await manager.send_status(batch_id, "cancelled", {
        "message": f"Batch cancelled. {cancelled_count} jobs affected.",
    })
    
    return {
        "batch_id": batch_id,
        "status": "cancelled",
        "cancelled_jobs": cancelled_count,
    }


@router.get("/list")
async def list_batches() -> List[Dict[str, Any]]:
    """List all batch jobs."""
    jobs = get_job_store()
    
    batches = [
        {
            "batch_id": job_id,
            "status": job.get("status"),
            "total_jobs": job.get("total_jobs"),
            "completed_jobs": job.get("completed_jobs"),
            "failed_jobs": job.get("failed_jobs"),
            "started_at": job.get("started_at"),
            "completed_at": job.get("completed_at"),
        }
        for job_id, job in jobs.items()
        if job.get("type") == "batch"
    ]
    
    # Sort by started_at descending
    batches.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    
    return batches

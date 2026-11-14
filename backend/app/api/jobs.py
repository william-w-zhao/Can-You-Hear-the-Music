"""Background jobs (analyse a building) and their live progress."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{job_id}")
def get_job(job_id: str):
    """Job state and log lines."""
    raise HTTPException(501, "Not implemented yet: get_job")


@router.get("/{job_id}/events")
def job_events(job_id: str):
    """Server-sent events: progress lines as they happen."""
    raise HTTPException(501, "Not implemented yet: job_events")

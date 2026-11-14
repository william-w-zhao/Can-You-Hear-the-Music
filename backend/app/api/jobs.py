"""Background building analysis and its current stage."""
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.pipeline.analyse_building import analyse_building
from app.pipeline.cache_files import write_json
from app.pipeline.materials import RoomMaterials
from app.sources.config import DATA

router = APIRouter()
logger = logging.getLogger(__name__)
worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="building-analysis")
lock = Lock()
jobs = {}
latest = {}


def latest_job(sid):
    with lock:
        job_id = latest.get(sid)
        return {**jobs[job_id], "job_id": job_id} if job_id else None


def run_job(job_id, sid):
    def report(message):
        with lock:
            jobs[job_id].update(message=message)

    try:
        review = analyse_building(sid, report)
    except (Exception, SystemExit) as exc:
        logger.error("Analysis failed for %s (%s)", sid, type(exc).__name__)
        message = str(exc) if isinstance(exc, (ValueError, RuntimeError, SystemExit)) else ""
        with lock:
            jobs[job_id].update(status="failed", message=message or "The scan could not be analysed. Try again.")
        return

    with lock:
        if review is None:
            jobs[job_id].update(status="complete", message="Rooms are ready.", review=None)
        else:
            jobs[job_id].update(status="needs_materials", message="Review the materials for each room.", review=review)


def start_job(sid):
    with lock:
        job_id = latest.get(sid)
        if job_id and jobs[job_id]["status"] in ("running", "needs_materials"):
            return job_id
        job_id = uuid4().hex
        latest[sid] = job_id
        jobs[job_id] = {"sid": sid, "status": "running", "message": "Waiting to start analysis", "review": None}
        worker.submit(run_job, job_id, sid)
        return job_id


@router.get("/{job_id}")
def get_job(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Analysis job not found.")
        return {**job, "job_id": job_id}


@router.post("/{job_id}/materials")
def submit_materials(job_id: str, materials: dict[str, RoomMaterials]):
    with lock:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Analysis job not found.")
        if job["status"] != "needs_materials":
            raise HTTPException(409, "This job is no longer waiting for material labels.")
        room_ids = {room["id"] for room in job["review"]["rooms"]}
        if materials.keys() != room_ids:
            raise HTTPException(422, "Provide materials for every room in this scan.")
        sid = job["sid"]
        write_json(DATA / sid / "materials.json", {
            "labelled_by": "Reviewed in the building dashboard",
            "rooms": {room_id: material.model_dump() for room_id, material in materials.items()},
        })
        job.update(status="running", message="Calculating room echo times", review=None)
        worker.submit(run_job, job_id, sid)
    return {"job_id": job_id}

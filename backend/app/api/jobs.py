"""Background building analysis and its current stage."""
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.pipeline.analyse_building import analyse_building
from app.pipeline.cache_files import write_json
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


def save_materials(sid, materials, room_ids):
    """Save reviewed labels and calculate echo times. Works even if the job that asked for them was lost
    (jobs live in memory, so a backend restart forgets them)."""
    if materials.keys() != set(room_ids):
        raise HTTPException(422, "Provide materials for every room in this scan.")
    with lock:
        job_id = latest.get(sid)
        if job_id and jobs[job_id]["status"] == "running":
            raise HTTPException(409, "This scan is already being analysed. Wait for it to finish.")
        write_json(DATA / sid / "materials.json", {
            "labelled_by": "Reviewed in the building dashboard",
            "rooms": {room_id: material.model_dump() for room_id, material in materials.items()},
        })
        if not job_id or jobs[job_id]["status"] != "needs_materials":
            job_id = uuid4().hex
            latest[sid] = job_id
            jobs[job_id] = {"sid": sid}
        jobs[job_id].update(status="running", message="Calculating room echo times", review=None)
        worker.submit(run_job, job_id, sid)
    return {"job_id": job_id}

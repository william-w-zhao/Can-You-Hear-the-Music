"""
FastAPI entry point for the React app.

    cd backend && uvicorn app.main:app --reload --port 8000

The frontend (Vite, :5173) proxies /api/* here. /data/* serves the shared cache in <project>/data/.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import acoustics, agent, buildings, jobs, rooms
from app.sources.config import DATA

app = FastAPI(title="Can You Hear the Music", version="0.1.0")

# Only the local frontend may call the API (it runs paid API calls with our keys).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(buildings.router, prefix="/api/buildings", tags=["buildings"])
app.include_router(rooms.router, prefix="/api/rooms", tags=["rooms"])
app.include_router(acoustics.router, prefix="/api/acoustics", tags=["acoustics"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(agent.router, prefix="/api/agent", tags=["agent"])

DATA.mkdir(exist_ok=True)
app.mount("/data", StaticFiles(directory=DATA), name="data")


@app.get("/api/health")
def health():
    return {"ok": True}

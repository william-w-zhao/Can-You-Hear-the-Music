"""Echo times and what-ifs for a room."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{room_id}")
def get_acoustics(room_id: str):
    """Echo time per band, likely range, verdict, impulse-response settings for the browser player. From pipeline.acoustics."""
    raise HTTPException(501, "Not implemented yet: get_acoustics")


@router.post("/{room_id}/what-if")
def what_if(room_id: str):
    """Same, for changed materials/contents in the request body. Pure computation, no side effects."""
    raise HTTPException(501, "Not implemented yet: what_if")


@router.get("/{room_id}/render.wav")
def render_wav(room_id: str):
    """Optional: a rendered WAV of the voice in this room (for reports or the agent)."""
    raise HTTPException(501, "Not implemented yet: render_wav")

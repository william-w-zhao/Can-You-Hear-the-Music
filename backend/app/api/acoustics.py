"""Echo times and what-ifs for a room."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.cache import read_scan_file
from app.pipeline.acoustics import BANDS, CONTENTS, MATERIALS, room_acoustics
from app.sources.config import AUDIO

router = APIRouter()
cached_router = APIRouter(prefix="/{sid}/rooms/{room_id}/acoustics", tags=["acoustics"])


class MaterialOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    floor: str | None = None
    ceiling: str | None = None
    walls: str | None = None
    glass_m2: float | None = Field(default=None, ge=0)
    furnishing: str | None = None


def cached_room(sid: str, room_id: str) -> tuple[dict, dict]:
    analysis = read_scan_file(sid, "acoustics.json")
    for room in analysis["rooms"]:
        if room["id"] == room_id:
            return analysis, room
    raise HTTPException(404, "Unknown room in this scan")


@cached_router.get("")
def get_acoustics(sid: str, room_id: str):
    """Return the saved metrics and supported what-if choices for one room."""
    analysis, room = cached_room(sid, room_id)
    return {
        "bands_hz": analysis.get("bands_hz", BANDS),
        "voice_url": "/audio/voice.wav" if analysis.get("voice") and (AUDIO / "voice.wav").is_file() else None,
        "material_options": {key: value["name"] for key, value in MATERIALS.items()},
        "furnishing_options": list(CONTENTS),
        "room": room,
    }


@cached_router.post("/what-if")
def what_if(sid: str, room_id: str, overrides: MaterialOverrides):
    """Recalculate a room with the requested overrides without writing to the cache."""
    changes = overrides.model_dump(exclude_none=True)
    for field in changes.keys() & {"floor", "ceiling", "walls"}:
        if changes[field] not in MATERIALS:
            raise HTTPException(422, f"Unknown material for {field}")
    if "furnishing" in changes and changes["furnishing"] not in CONTENTS:
        raise HTTPException(422, "Unknown furnishing category")
    _, room = cached_room(sid, room_id)
    scenario = {**room, **changes}
    return {**scenario, **room_acoustics(room, scenario)}


@router.get("/{room_id}/render.wav")
def render_wav(room_id: str):
    """Optional: a rendered WAV of the voice in this room (for reports or the agent)."""
    raise HTTPException(501, "Not implemented yet: render_wav")

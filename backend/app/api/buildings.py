"""Buildings: the picker and a building's details."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("")
def list_buildings():
    """All buildings in the kit (from sources.costar_kit catalog), minus outdoor-only scans. Supports search, city, kind, sort. Port of backend/prototypes/explorer.py /api/catalog."""
    raise HTTPException(501, "Not implemented yet: list_buildings")


@router.get("/{sid}")
def get_building(sid: str):
    """One building: CoStar records + Matterport basics + whether it has been analysed. Port of /api/kit/<sid> + bundle.json."""
    raise HTTPException(501, "Not implemented yet: get_building")


@router.post("/{sid}/analyse")
def analyse_building(sid: str):
    """Start a background job: fetch -> point cloud -> rooms -> materials -> acoustics. Returns a job id (see jobs.py)."""
    raise HTTPException(501, "Not implemented yet: analyse_building")


@router.get("/{sid}/rooms")
def list_rooms(sid: str):
    """Room outlines (floor-plan pixels), areas, ceiling heights, labels, from data/<sid>/rooms.json."""
    raise HTTPException(501, "Not implemented yet: list_rooms")

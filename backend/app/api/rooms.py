"""One room: geometry, materials and panoramas."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/{room_id}")
def get_room(room_id: str):
    """Room geometry, materials (with confidence), panorama ids. room_id = '<sid>:<rid>'."""
    raise HTTPException(501, "Not implemented yet: get_room")


@router.put("/{room_id}/materials")
def confirm_materials(room_id: str):
    """A person confirms or corrects material labels (the agent's human-approval step writes here too)."""
    raise HTTPException(501, "Not implemented yet: confirm_materials")

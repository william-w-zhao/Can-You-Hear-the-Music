"""Buildings: the picker and a building's details."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from app.api.cache import read_scan_file, scan_directory
from app.sources import costar_kit
from app.sources.config import DATA, KIT

router = APIRouter()


def analysed_scans() -> set[str]:
    return {
        path.parent.name for path in DATA.glob("*/acoustics.json")
        if path.is_file() and path.with_name("rooms.json").is_file()
    }


def catalog_rows() -> list[dict]:
    if costar_kit.CATALOG.is_file():
        return costar_kit.load_catalog()
    if all((KIT / name).is_file() for name in ("commercial-properties.csv", "residential-listings.csv")):
        rows, _ = costar_kit.build()
        return rows
    return []


@router.get("")
def list_buildings():
    """List catalog scans and mark those ready for listening."""
    analysed = analysed_scans()
    rows = {row["sid"]: row for row in catalog_rows()}
    for sid in analysed - rows.keys():
        rows[sid] = {"sid": sid}
    summaries = [{**row, "analysed": sid in analysed} for sid, row in rows.items()]
    return sorted(summaries, key=lambda row: (not row["analysed"], row.get("address", ""), row["sid"]))


@router.get("/{sid}")
def get_building(sid: str):
    """Return catalog details and the cached scan name when available."""
    directory = scan_directory(sid)
    row = next((row for row in catalog_rows() if row["sid"] == sid), None)
    analysed = sid in analysed_scans()
    if not (row or analysed or (directory / "bundle.json").is_file()):
        raise HTTPException(404, "Unknown scan")
    summary = {**(row or {}), "sid": sid, "analysed": analysed}
    if (directory / "bundle.json").is_file():
        bundle = read_scan_file(sid, "bundle.json")
        name = bundle.get("matterport", {}).get("basics", {}).get("name")
        if name:
            summary["name"] = name
    return summary


@router.post("/{sid}/analyse")
def analyse_building(sid: str):
    """Start a background job: fetch -> point cloud -> rooms -> materials -> acoustics. Returns a job id (see jobs.py)."""
    raise HTTPException(501, "Not implemented yet: analyse_building")


@router.get("/{sid}/rooms")
def list_rooms(sid: str):
    """Return cached room outlines in floor-plan pixels."""
    geometry = read_scan_file(sid, "rooms.json")
    floorplan = geometry.get("floorplan")
    if floorplan:
        floorplan = {**floorplan, "url": f"/data/{sid}/{quote(floorplan['file'], safe='')}"}
    if (scan_directory(sid) / "acoustics.json").is_file():
        results = read_scan_file(sid, "acoustics.json")
        labels = {room["id"]: room.get("type") for room in results["rooms"]}
    else:
        labels = {}
    return {
        "floorplan": floorplan,
        "rooms": [
            {**room, "label": labels.get(room["id"]) or room.get("matterport_label") or room["id"]}
            for room in geometry["rooms"]
        ],
    }

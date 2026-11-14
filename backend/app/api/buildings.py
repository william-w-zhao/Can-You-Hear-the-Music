"""Buildings: the picker and a building's details."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from app.api.cache import read_scan_file, scan_directory
from app.api.jobs import latest_job, start_job
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
    for summary in summaries:
        sid = summary["sid"]
        if sid in analysed and (DATA / sid / "preview.jpg").is_file():
            summary["preview_url"] = f"/data/{quote(sid, safe='')}/preview.jpg"
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
    if (directory / "vision.json").is_file():
        vision = read_scan_file(sid, "vision.json")
        summary["vision_pending"] = any(vision[part]["status"] == "failed" for part in ("indoor", "aerial"))
    else:
        summary["vision_pending"] = True
    job = latest_job(sid)
    if job and job["status"] in ("running", "needs_materials"):
        summary["analysis_job_id"] = job["job_id"]
    return summary


@router.post("/{sid}/analyse", status_code=202)
def analyse_building(sid: str):
    """Start or resume background analysis for this scan."""
    get_building(sid)  # Validate the scan before scheduling work.
    return {"job_id": start_job(sid)}


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


@router.get("/{sid}/surroundings")
def get_surroundings(sid: str):
    """Keep image detections and mapped footprints as separate evidence sources."""
    directory = scan_directory(sid)
    vision = (read_scan_file(sid, "vision.json")["aerial"]
              if (directory / "vision.json").is_file() else {"status": "pending"})
    osm_count = len(read_scan_file(sid, "osm.json")) if (directory / "osm.json").is_file() else None
    return {
        **vision,
        "image_url": f"/data/{sid}/ortho.jpg" if (directory / "ortho.jpg").is_file() else None,
        "mapped_buildings": osm_count,
    }

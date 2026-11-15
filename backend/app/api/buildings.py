"""Buildings: the picker and a building's details."""
from urllib.parse import quote

from fastapi import APIRouter, HTTPException

from app.api.cache import read_scan_file, scan_directory
from app.api.jobs import latest_job, save_materials, start_job
from app.pipeline.materials import RoomMaterials
from app.sources import costar_kit
from app.sources.config import DATA, KIT
from app.sources.matterport import MODEL_NAME_FILE

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


def bundle_details(sid):
    """Display metadata from a downloaded scan or from a name-only lookup."""
    directory = scan_directory(sid)
    if not (directory / "bundle.json").is_file():
        return read_scan_file(sid, MODEL_NAME_FILE) if (directory / MODEL_NAME_FILE).is_file() else {}
    bundle = read_scan_file(sid, "bundle.json")
    name = bundle.get("matterport", {}).get("basics", {}).get("name")
    kind = (bundle.get("site") or {}).get("segment")
    return {key: value for key, value in (("name", name), ("address", name), ("kind", kind)) if value}


@router.get("")
def list_buildings():
    """List catalog scans and mark those ready for listening."""
    analysed = analysed_scans()
    rows = {row["sid"]: row for row in catalog_rows()}
    for sid in analysed - rows.keys():
        rows[sid] = {"sid": sid, **bundle_details(sid)}
    summaries = [{**row, "analysed": sid in analysed} for sid, row in rows.items()]
    for summary in summaries:
        sid = summary["sid"]
        if not (summary.get("name") or summary.get("address")):
            # Some catalog rows have a blank address; the scan's own name fills the gap.
            summary.update({key: value for key, value in bundle_details(sid).items() if not summary.get(key)})
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
    name = bundle_details(sid).get("name")
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


@router.post("/{sid}/materials", status_code=202)
def save_building_materials(sid: str, materials: dict[str, RoomMaterials]):
    """Save the reviewed material labels for every room and calculate echo times."""
    rooms = read_scan_file(sid, "rooms.json")["rooms"]
    return save_materials(sid, materials, [room["id"] for room in rooms])


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

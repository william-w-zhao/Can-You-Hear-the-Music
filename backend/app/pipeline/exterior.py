"""What the building's outside walls and windows are made of, from photos of the outside.

Evidence, best first:
1. Matterport panoramas taken outside (their position falls well outside every room): the four side views.
2. The CoStar listing's photo captions, alt text and keywords ("single-story home with gray siding").
3. When neither shows the outside (an office suite), the room photos with the most glass, for the windows.

A vision model reads the evidence and picks the wall construction and window type from fixed lists. Each choice maps
to a traffic-noise insulation value (Rw + Ctr, typical published ranges). With no evidence at all, the building type
and year give a default. The result is cached as exterior.json and always says what it was based on.
"""
import base64
import json
from io import BytesIO
from typing import Literal

from pydantic import BaseModel, Field

from app.pipeline.cache_files import write_json
from app.sources.config import DATA

# Traffic-weighted sound insulation, Rw + Ctr in dB, for the whole wall (typical values for each construction).
WALLS = {
    "stucco_wood_frame": ("Stucco on a wood frame", 40.0),
    "wood_siding": ("Wood or fibre-cement siding on a wood frame", 36.0),
    "brick_veneer": ("Brick veneer on a frame", 48.0),
    "solid_masonry": ("Solid brick or stone", 52.0),
    "concrete_block": ("Concrete block", 47.0),
    "concrete": ("Cast concrete", 54.0),
    "glass_curtain_wall": ("Glass curtain wall", 32.0),
    "metal_panel": ("Metal panel", 38.0),
}
WINDOWS = {
    "single_pane": ("Single-pane glass", 24.0),
    "double_pane": ("Double-pane glass", 30.0),
    "laminated_or_acoustic": ("Laminated or acoustic glass", 35.0),
}
MIN_OUTSIDE_M = 2.5            # a panorama this far outside every room was taken outdoors, not in a closet


class WallShare(BaseModel):
    material: Literal[tuple(WALLS)]
    share: float = Field(ge=0, le=1, description="Fraction of the outside wall area with this construction.")


class ExteriorAssessment(BaseModel):
    subject_visible: bool = Field(description="True if the scanned building itself is visible in the photos.")
    walls: list[WallShare] = Field(min_length=1, max_length=4)
    windows: Literal[tuple(WINDOWS)]
    evidence: str = Field(max_length=400, description="What in the photos supports these choices.")
    confidence: float = Field(ge=0, le=1)


def default_assessment(segment, year):
    office = segment and segment.lower() not in ("residential", "house", "home")
    walls = [{"material": "concrete" if office else "stucco_wood_frame", "share": 1.0}]
    windows = "double_pane" if (year and year >= 1980) or office else "single_pane"
    return {"subject_visible": False, "walls": walls, "windows": windows, "confidence": 0.3,
            "evidence": "No outside photos; typical construction for the building type and year."}


def outdoor_views(sid, limit=3):
    """JPEG bytes for the side views of panoramas taken outdoors, nearest the building first."""
    from app.pipeline.facades import point_in_polygon
    from app.pipeline.panoramas import download_face, skyboxes
    from app.sources.traffic import segment_distance

    directory = DATA / sid
    bundle = json.loads((directory / "bundle.json").read_text())
    geometry = json.loads((directory / "rooms.json").read_text())
    plan = geometry["floorplan"]
    polygons = [room["polygon_px"] for room in geometry["rooms"] if room.get("polygon_px")]
    candidates = []
    for pano in bundle["matterport"].get("panos", []):
        x = (pano["position"]["x"] - plan["origin"]["x"]) * plan["resolution"]
        y = plan["height"] - (pano["position"]["y"] - plan["origin"]["y"]) * plan["resolution"]
        if any(point_in_polygon(x, y, polygon) for polygon in polygons):
            continue
        gap = min(segment_distance(x, y, *a, *b) for polygon in polygons
                  for a, b in zip(polygon, polygon[1:] + polygon[:1])) / plan["resolution"]
        if gap >= MIN_OUTSIDE_M:
            candidates.append((gap, pano["id"]))
    if not candidates:
        return []
    sky = skyboxes(sid)
    images = []
    for _, pano_id in sorted(candidates)[:limit]:          # closest outdoor spots show the building best
        for face in (sky.get(pano_id) or [])[1:5]:
            image, _ = download_face(face)
            image.thumbnail((768, 768))
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            images.append(buffer.getvalue())
    return images


def listing_text(sid):
    bundle = json.loads((DATA / sid / "bundle.json").read_text())
    media = (((bundle.get("costar") or {}).get("listing") or {}).get("media")) or []
    lines = []
    for item in media:
        words = [item.get("caption"), item.get("altText"), ", ".join(item.get("computerVisionKeywords") or [])]
        text = " | ".join(word for word in words if word)
        if text and any(key in text.lower() for key in ("exterior", "front", "home", "house", "siding", "stucco",
                                                         "brick", "window", "facade", "building", "back")):
            lines.append(text)
    return lines[:20]


def glass_room_views(sid, limit=2):
    directory = DATA / sid
    rooms = json.loads((directory / "materials.json").read_text())["rooms"] if (directory / "materials.json").is_file() else {}
    geometry = json.loads((directory / "rooms.json").read_text())["rooms"]
    order = sorted(range(len(geometry)), key=lambda i: -(rooms.get(geometry[i]["id"], {}).get("glass_m2") or 0))
    from PIL import Image

    images = []
    with Image.open(directory / "room_sheet.jpg") as sheet:
        height = sheet.height // len(geometry)
        for index in order[:limit]:
            row = sheet.crop((0, index * height, sheet.width, (index + 1) * height)).convert("RGB")
            buffer = BytesIO()
            row.save(buffer, format="JPEG", quality=85)
            images.append(buffer.getvalue())
    return images


def assess_exterior(sid, *, settings=None, segment=None, year=None, refresh=False):
    """Cached exterior.json: wall shares, window type, insulation values and what they rest on."""
    path = DATA / sid / "exterior.json"
    if path.is_file() and not refresh:
        return json.loads(path.read_text())
    images, basis = [], None
    try:
        images = outdoor_views(sid)
        basis = "outdoor panoramas" if images else None
    except Exception:
        images = []
    text = listing_text(sid)
    if not images:
        try:
            images = glass_room_views(sid)
            basis = "room photos (no outdoor views)" if images else None
        except OSError:
            images = []
    result = None
    if settings and (images or text):
        from langchain_core.messages import HumanMessage

        prompt = (
            "These photos were taken at a scanned building"
            + (" from outside, standing next to it; neighbouring buildings may also appear. The scanned building is "
               "the one the camera is closest to." if basis == "outdoor panoramas" else
               ". They are inside views; judge the windows and, if visible, the outside wall.")
            + " Choose the outside wall construction (with shares if it is mixed, such as a brick front and stucco "
            "sides) from: " + ", ".join(f"{k} ({v[0]})" for k, v in WALLS.items())
            + ". Choose the main window type from: " + ", ".join(f"{k} ({v[0]})" for k, v in WINDOWS.items())
            + ". Old wood or steel sash, leaded or divided-light windows are usually single_pane; modern vinyl or "
            "aluminium windows with thick frames are usually double_pane. Use low confidence when unsure."
            + (f" Building type: {segment}." if segment else "") + (f" Year built: {year}." if year else "")
            + (" Listing photo descriptions: " + " / ".join(text) if text else "")
        )
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image", "mime_type": "image/jpeg", "base64": base64.b64encode(image).decode("ascii")}
            for image in images[:12]]
        try:
            answer = settings.structured(ExteriorAssessment, max_tokens=900).invoke([HumanMessage(content=content)])
            result = answer.model_dump() if answer else None
        except Exception:
            result = None
    if result is None:
        result = default_assessment(segment, year)
        basis = "building type and year"
    total = sum(item["share"] for item in result["walls"]) or 1.0
    shares = [{**item, "share": round(item["share"] / total, 2)} for item in result["walls"]]
    import math

    wall_r = -10 * math.log10(sum(item["share"] * 10 ** (-WALLS[item["material"]][1] / 10) for item in shares))
    record = {**result, "walls": shares, "basis": basis or "listing descriptions",
              "wall_insulation_db": round(wall_r, 1), "window_insulation_db": WINDOWS[result["windows"]][1],
              "wall_label": ", ".join(f"{WALLS[i['material']][0]} {i['share']:.0%}" for i in shares),
              "window_label": WINDOWS[result["windows"]][0], "photos_used": len(images)}
    write_json(path, record)
    return record

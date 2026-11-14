"""Echo times and what-ifs for a room."""
from hashlib import sha256
import json
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.agent.room_review import RoomReview, review_tasks, run_review
from app.api.cache import read_scan_file, scan_directory
from app.pipeline.acoustics import BANDS, CONTENTS, MATERIALS, room_acoustics
from app.pipeline.cache_files import write_json
from app.pipeline.dimensions import room_dimensions
from app.pipeline.object_groups import detection_id, group_detections
from app.pipeline.panoramas import face_path, recover_face, skyboxes
from app.pipeline.vision import FACE_ORDER, SHEET_MARGIN, VIEWS
from app.sources.config import AUDIO
from app.sources.review_model import resolve_review_model

router = APIRouter()
cached_router = APIRouter(prefix="/{sid}/rooms/{room_id}/acoustics", tags=["acoustics"])
review_lock = Lock()


class ObjectMatch(BaseModel):
    detection_ids: tuple[str, str]


class ObjectDecision(ObjectMatch):
    decision: Literal["same", "separate", "reset"]


class ApprovedRoomReview(RoomReview):
    revision: str


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
            materials = room_reviews(sid).get(room_id, {}).get("materials", {})
            if materials:
                updated = {**room, **materials}
                return analysis, {**updated, **room_acoustics(room, updated)}
            return analysis, room
    raise HTTPException(404, "Unknown room in this scan")


def indoor_evidence(sid, room_id, directory):
    if not (directory / "vision.json").is_file():
        return {"status": "pending"}, 0
    indoor = read_scan_file(sid, "vision.json")["indoor"]
    evidence = indoor.get("rooms", {}).get(room_id, {"status": indoor["status"]})
    labels = room_reviews(sid).get(room_id, {}).get("labels", {})
    if labels:
        evidence = {**evidence, "detections": reviewed_hits(evidence.get("detections", []), labels)}
    return evidence, (indoor.get("width", 0) - SHEET_MARGIN) // len(VIEWS)


def reviewed_hits(hits, labels):
    reviewed = []
    for hit in hits:
        proposal = labels.get(detection_id(hit))
        if proposal == "dismiss":
            continue
        if proposal:
            hit = {**hit, "original_label": hit.get("original_label", hit["label"]),
                   "label": hit["label"] if proposal == "keep" else proposal, "needs_review": False}
        reviewed.append(hit)
    return reviewed


def room_reviews(sid):
    return read_scan_file(sid, "room_reviews.json") if (scan_directory(sid) / "room_reviews.json").is_file() else {}


def object_decisions(sid, room_id):
    reviewed = room_reviews(sid).get(room_id, {})
    if "matches" in reviewed:
        return reviewed["matches"]
    if (scan_directory(sid) / "object_reviews.json").is_file():
        return read_scan_file(sid, "object_reviews.json").get(room_id, {})
    return {}


@cached_router.get("")
def get_acoustics(sid: str, room_id: str):
    """Return the saved metrics and supported what-if choices for one room."""
    analysis, room = cached_room(sid, room_id)
    settings, model_error = resolve_review_model()
    geometry = read_scan_file(sid, "rooms.json")
    row = next((index for index, item in enumerate(geometry["rooms"]) if item["id"] == room_id), None)
    outline = geometry["rooms"][row] if row is not None else None
    directory = scan_directory(sid)
    evidence, face_size = indoor_evidence(sid, room_id, directory)
    hits = evidence.get("detections", [])
    if hits and face_size > 0:
        decisions = object_decisions(sid, room_id)
        evidence = {**evidence, "detections": [{**hit, "id": detection_id(hit)} for hit in hits],
                    "inventory": group_detections(hits, face_size, decisions),
                    "can_suggest_match": settings is not None}
    sheet = directory / "room_sheet.jpg"
    if row is not None and outline is not None and outline.get("panorama_available", True):
        try:
            with Image.open(sheet) as image:
                width, height = image.size
        except OSError:
            width, height = 0, 0
        size, remainder = divmod(height, len(geometry["rooms"]))
        if size and not remainder and width == SHEET_MARGIN + size * len(VIEWS):
            evidence = {
                **evidence,
                "image_url": f"/data/{sid}/{sheet.name}",
                "image_width": width,
                "image_height": height,
                "image_row": [0, row * size, width, size],
                "views": [
                    {"name": name, "viewport": [SHEET_MARGIN + column * size, row * size, size, size],
                     "photo_url": f"/api/buildings/{sid}/rooms/{room_id}/acoustics/photos/{FACE_ORDER[column]}"}
                    for column, name in enumerate(VIEWS)
                ],
            }
    return {
        "bands_hz": analysis.get("bands_hz", BANDS),
        "voice_url": "/audio/voice.wav" if analysis.get("voice") and (AUDIO / "voice.wav").is_file() else None,
        "material_options": {key: value["name"] for key, value in MATERIALS.items()},
        "furnishing_options": list(CONTENTS),
        "room": room,
        "dimensions": room_dimensions(outline, geometry) if outline else None,
        "object_evidence": evidence,
        "can_run_room_review": bool(settings and evidence.get("views")),
        "review_model": settings.identifier if settings else None,
        "review_model_error": model_error,
    }


def match_evidence(sid, room_id, directory, match):
    evidence, face_size = indoor_evidence(sid, room_id, directory)
    detections = evidence.get("detections", [])
    by_id = {detection_id(hit): hit for hit in detections}
    first, second = sorted(match.detection_ids)
    if face_size <= 0 or first == second or first not in by_id or second not in by_id:
        raise HTTPException(409, "The detections have changed. Refresh the room and try again.")
    return detections, face_size, f"{first}:{second}", [by_id[first], by_id[second]]


@cached_router.post("/object-review")
def review_objects(sid: str, room_id: str, match: ObjectDecision):
    directory = scan_directory(sid)
    with review_lock:
        hits, size, pair, _ = match_evidence(sid, room_id, directory, match)
        saved = room_reviews(sid)
        decisions = object_decisions(sid, room_id)
        if match.decision == "reset":
            decisions.pop(pair, None)
        else:
            decisions[pair] = match.decision
        try:
            inventory = group_detections(hits, size, decisions)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        saved.setdefault(room_id, {})["matches"] = decisions
        write_json(directory / "room_reviews.json", saved)
    return inventory


def room_review_context(sid, room_id):
    details = get_acoustics(sid, room_id)
    evidence = details["object_evidence"]
    tasks = review_tasks(details["room"], evidence)
    directory = scan_directory(sid)
    sheet = directory / "room_sheet.jpg"
    if not evidence.get("image_row") or not sheet.is_file():
        raise HTTPException(409, "Room photos are needed for this review.")
    snapshot = [tasks, evidence.get("detections"), room_reviews(sid).get(room_id),
                object_decisions(sid, room_id), sheet.stat().st_mtime_ns]
    revision = sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
    return details, tasks, revision


@cached_router.post("/room-review")
def propose_room_review(sid: str, room_id: str):
    settings, model_error = resolve_review_model()
    if not settings:
        raise HTTPException(503, model_error)
    details, tasks, revision = room_review_context(sid, room_id)
    _, y, _, size = details["object_evidence"]["image_row"]
    outline = next(room for room in read_scan_file(sid, "rooms.json")["rooms"] if room["id"] == room_id)
    try:
        proposals = run_review(scan_directory(sid), outline, y // size, size, tasks, settings)
    except Exception as exc:
        raise HTTPException(502, "Deep Agents could not finish this review. Check the model configuration and try again.") from exc
    if not proposals:
        raise HTTPException(502, "The agent produced no proposals backed by the room photos.")
    return {"revision": revision, "proposals": proposals, "model": settings.identifier,
            "descriptions": {target: task["description"] for target, task in tasks.items()}}


@cached_router.post("/room-review/approve")
def approve_room_review(sid: str, room_id: str, approved: ApprovedRoomReview):
    with review_lock:
        details, tasks, revision = room_review_context(sid, room_id)
        if revision != approved.revision:
            raise HTTPException(409, "Room evidence or review decisions changed. Run the review again.")
        saved = room_reviews(sid)
        review = saved.setdefault(room_id, {})
        labels = review.setdefault("labels", {})
        materials = review.setdefault("materials", {})
        matches = object_decisions(sid, room_id)
        for item in approved.proposals:
            task = tasks.get(item.target)
            if not task or item.value not in task["choices"] or item.view not in task["views"]:
                raise HTTPException(422, "A proposal is outside the supported choices for this room.")
            if item.target.startswith("pair:"):
                matches[item.target.removeprefix("pair:")] = item.value
            elif item.target.startswith("label:"):
                labels[item.target.removeprefix("label:")] = item.value
            else:
                materials[item.target] = item.value
        review["matches"] = matches
        evidence = details["object_evidence"]
        if evidence.get("detections"):
            hits = reviewed_hits(evidence["detections"], labels)
            try:
                group_detections(hits, evidence["image_row"][3], matches)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        write_json(scan_directory(sid) / "room_reviews.json", saved)
    return get_acoustics(sid, room_id)


@cached_router.post("/object-review/suggest")
def suggest_object_match(sid: str, room_id: str, match: ObjectMatch):
    directory = scan_directory(sid)
    _, _, _, hits = match_evidence(sid, room_id, directory, match)
    settings, model_error = resolve_review_model()
    if not settings:
        raise HTTPException(503, model_error)
    from app.pipeline.object_review import suggest_match

    try:
        result = suggest_match(directory, hits, settings)
        if result is None:
            raise ValueError("No match suggestion returned")
        return {**result.model_dump(), "model": settings.identifier}
    except Exception as exc:
        raise HTTPException(502, "The model could not compare these detections.") from exc


@cached_router.get("/photos/{face_index}")
def panorama_photo(sid: str, room_id: str, face_index: int):
    """Serve one original face, recovering it from Matterport for older room caches."""
    directory = scan_directory(sid)
    rooms = read_scan_file(sid, "rooms.json")["rooms"]
    row = next((index for index, room in enumerate(rooms) if room["id"] == room_id), None)
    if face_index not in FACE_ORDER or row is None or not rooms[row].get("panorama_available", True):
        raise HTTPException(404, "Panorama view unavailable")
    path = face_path(directory, rooms[row], face_index)
    if not path.is_file():
        try:
            with Image.open(directory / "room_sheet.jpg") as sheet:
                size, remainder = divmod(sheet.height, len(rooms))
                if not size or remainder or sheet.width != SHEET_MARGIN + size * len(VIEWS):
                    raise ValueError("Unexpected contact sheet layout")
                x = SHEET_MARGIN + FACE_ORDER.index(face_index) * size
                y = row * size
                thumbnail = sheet.crop((x, y, x + size, y + size)).convert("RGB")
            path = recover_face(directory, rooms[row], face_index, thumbnail, skyboxes(sid))
        except (Exception, SystemExit) as exc:
            raise HTTPException(503, "Original panorama view unavailable") from exc
    if path is None:
        raise HTTPException(404, "Original panorama view could not be matched")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


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

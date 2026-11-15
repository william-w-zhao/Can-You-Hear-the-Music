"""Echo times and what-ifs for a room."""
from hashlib import sha256
import json
from threading import Lock
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.agent.room_review import Proposal, RoomReview, review_tasks, run_review
from app.api.cache import read_scan_file, scan_directory
from app.pipeline.acoustics import BANDS, CONTENTS, MATERIALS, room_acoustics
from app.pipeline.cache_files import write_json
from app.pipeline.dimensions import room_dimensions
from app.pipeline.object_groups import detection_id, group_detections, merge_decisions, reviewed_hits, split_decisions
from app.pipeline.panorama_views import render as render_view
from app.pipeline.panoramas import face_path, recover_face, skyboxes
from app.pipeline.vision import FACE_ORDER, SHEET_MARGIN, VIEWS
from app.sources.config import AUDIO
from app.sources.review_model import resolve_review_model

cached_router = APIRouter(prefix="/{sid}/rooms/{room_id}/acoustics", tags=["acoustics"])
review_lock = Lock()


class ObjectMatch(BaseModel):
    detection_ids: tuple[str, str]


class ObjectDecision(ObjectMatch):
    decision: Literal["same", "separate", "reset"]


class ObjectKeep(BaseModel):
    detection_ids: list[str] = Field(min_length=1, max_length=40)


class ObjectSelection(ObjectKeep):
    detection_ids: list[str] = Field(min_length=2, max_length=40)


class ApprovedRoomReview(RoomReview):
    revision: str
    proposals: list[Proposal] = Field(min_length=1)


class MaterialOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    floor: str | None = None
    ceiling: str | None = None
    walls: str | None = None
    glass_m2: float | None = Field(default=None, ge=0)
    wall_panel_m2: float | None = Field(default=None, ge=0)
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
    vision = read_scan_file(sid, "vision.json")
    indoor = vision["indoor"]
    evidence = indoor.get("rooms", {}).get(room_id, {"status": indoor["status"]})
    if vision.get("model"):
        evidence = {**evidence, "model": vision["model"]}
    review = room_reviews(sid).get(room_id, {})
    labels = review.get("labels", {})
    kept = set(review.get("kept", []))
    if labels or kept:
        hits = reviewed_hits(evidence.get("detections", []), labels)
        evidence = {**evidence, "detections": mark_kept(hits, kept)}
    return evidence, (indoor.get("width", 0) - SHEET_MARGIN) // len(VIEWS)


def mark_kept(hits, kept):
    # Confirmation affects the inventory without changing the original score or automatic matching.
    return [{**hit, "kept": True} if detection_id(hit) in kept else hit for hit in hits]


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
        "materials_source": analysis.get("materials_source"),
        "reviewed_surfaces": sorted(room_reviews(sid).get(room_id, {}).get("materials", {})),
        "absorption_coefficients": analysis.get("materials", MATERIALS),
        "furnishing_allowances": analysis.get("contents", CONTENTS),
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


def save_selection(sid, room_id, selection, action):
    """Apply a manual inventory decision and return the persisted grouping."""
    directory = scan_directory(sid)
    with review_lock:
        evidence, size = indoor_evidence(sid, room_id, directory)
        hits = evidence.get("detections", [])
        known = {detection_id(hit) for hit in hits}
        ids = list(dict.fromkeys(selection.detection_ids))
        minimum = 1 if action == "keep" else 2
        if size <= 0 or len(ids) < minimum or not set(ids) <= known:
            raise HTTPException(409, "The detections have changed. Refresh the room and try again.")
        saved = room_reviews(sid)
        review = saved.setdefault(room_id, {})
        kept = set(review.get("kept", []))
        decisions = object_decisions(sid, room_id)
        try:
            if action == "split":
                # Undoing a saved merge keeps its confirmed detections visible as separate objects.
                confirmed = {key for group in group_detections(hits, size, decisions)["groups"] if group["confirmed"]
                             for key in group["detection_ids"]}
                kept.update(confirmed.intersection(ids))
                decisions = split_decisions(hits, size, decisions, ids)
            else:
                kept.update(ids)
                if action == "merge":
                    decisions = merge_decisions(hits, size, decisions, ids)
            inventory = group_detections(mark_kept(hits, kept), size, decisions)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        review.update(matches=decisions, kept=sorted(kept))
        write_json(directory / "room_reviews.json", saved)
    return inventory


@cached_router.post("/object-review/merge")
def merge_objects(sid: str, room_id: str, selection: ObjectSelection):
    """Treat all the selected detections as one physical object."""
    return save_selection(sid, room_id, selection, "merge")


@cached_router.post("/object-review/split")
def split_objects(sid: str, room_id: str, selection: ObjectSelection):
    """Treat each selected detection as its own object."""
    return save_selection(sid, room_id, selection, "split")


@cached_router.post("/object-review/keep")
def keep_objects(sid: str, room_id: str, selection: ObjectKeep):
    """Count the selected groups as objects without joining them."""
    return save_selection(sid, room_id, selection, "keep")


def room_photo_context(sid, room_id):
    """Directory, room outline, contact-sheet row and face size for drawing on this room's panorama."""
    directory = scan_directory(sid)
    rooms = read_scan_file(sid, "rooms.json")["rooms"]
    row = next((index for index, room in enumerate(rooms) if room["id"] == room_id), None)
    if row is None or not rooms[row].get("panorama_available", True) or not (directory / "room_sheet.jpg").is_file():
        raise HTTPException(404, "Room photos unavailable")
    _, size = indoor_evidence(sid, room_id, directory)
    if size <= 0:
        raise HTTPException(404, "Run image analysis to see detections")
    return directory, rooms[row], row, size


def fetch_full_faces(sid, directory, outline, row, size, faces):
    """Best effort: replace thumbnails with original faces so drawn views are sharp. Never fails the request."""
    missing = [face for face in faces if not face_path(directory, outline, face).is_file()]
    if not missing:
        return
    try:
        sky = skyboxes(sid)
        with Image.open(directory / "room_sheet.jpg") as sheet:
            for face in missing:
                x = SHEET_MARGIN + FACE_ORDER.index(face) * size
                thumbnail = sheet.crop((x, row * size, x + size, (row + 1) * size)).convert("RGB")
                recover_face(directory, outline, face, thumbnail, sky)
    except (Exception, SystemExit):
        pass


def detection_view(sid, room_id, ids):
    """JPEG of a view framing the given detections, outlined and tagged A, B, ..."""
    directory, outline, row, size = room_photo_context(sid, room_id)
    evidence, _ = indoor_evidence(sid, room_id, directory)
    by_id = {detection_id(hit): hit for hit in evidence.get("detections", [])}
    if not ids or len(ids) > 4 or not all(i in by_id for i in ids):
        raise HTTPException(409, "The detections have changed. Refresh the room and try again.")
    hits = [by_id[i] for i in ids]
    fetch_full_faces(sid, directory, outline, row, size, {hit["face_index"] for hit in hits})
    return render_view(directory, outline, row, size, hits)


@cached_router.get("/object-review/view.jpg")
def object_view(sid: str, room_id: str, ids: str = Query(..., description="Comma-separated detection IDs (1 to 4)")):
    """A perspective view of the room with the chosen detections outlined, for comparing possible duplicates."""
    jpeg = detection_view(sid, room_id, [i for i in ids.split(",") if i])
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})


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


def apply_automatic_object_decisions(details, review, matches, proposals):
    """Apply clear results while retaining human decisions and uncertain matches."""
    labels = review.setdefault("labels", {})
    evidence = details["object_evidence"]
    hits = evidence.get("detections", [])
    size = evidence["image_row"][3]
    applied = []
    ready = [item for item in proposals if item.confidence == "high" and item.value != "unsure"]
    for item in ready:
        if item.target.startswith("label:"):
            hit_id = item.target.removeprefix("label:")
            if hit_id not in labels:
                labels[hit_id] = item.value
                applied.append(item)

    hits = reviewed_hits(hits, labels)
    faces = {hit["id"]: hit["face_index"] for hit in hits}
    # Record explicit separations before considering any merge in this run.
    pairs = sorted((item for item in ready if item.target.startswith("pair:")),
                   key=lambda item: item.value == "same")
    partners = {}
    for item in pairs:
        first, second = item.target.removeprefix("pair:").split(":")
        if item.value == "same" and {first, second} <= faces.keys():
            partners.setdefault((first, faces[second]), set()).add(second)
            partners.setdefault((second, faces[first]), set()).add(first)
    for item in pairs:
        pair = item.target.removeprefix("pair:")
        first, second = pair.split(":")
        if pair in matches or not {first, second} <= faces.keys():
            continue
        if item.value == "same":
            if len(partners[first, faces[second]]) > 1 or len(partners[second, faces[first]]) > 1:
                continue
            groups = group_detections(hits, size, matches)["groups"]
            left = next(group["detection_ids"] for group in groups if first in group["detection_ids"])
            right = next(group["detection_ids"] for group in groups if second in group["detection_ids"])
            if left == right:
                continue
            common_faces = {faces[key] for key in left} & {faces[key] for key in right}
            # A same-view duplicate may merge two boxes, but never join larger overlapping groups.
            if common_faces and not (len(left) == len(right) == 1 and faces[first] == faces[second]):
                continue
        trial = {**matches, pair: item.value}
        try:
            group_detections(hits, size, trial)
        except ValueError:
            continue
        matches[pair] = item.value
        applied.append(item)
    review["matches"] = matches
    return applied


@cached_router.post("/room-review")
def propose_room_review(sid: str, room_id: str):
    settings, model_error = resolve_review_model()
    if not settings:
        raise HTTPException(503, model_error)
    with review_lock:
        details, tasks, revision = room_review_context(sid, room_id)
    _, y, _, size = details["object_evidence"]["image_row"]
    outline = next(room for room in read_scan_file(sid, "rooms.json")["rooms"] if room["id"] == room_id)
    entries = list(tasks.items())
    proposals = []

    def render_task(task_id):
        # "pair:<a>:<b>" or "label:<a>" -> the detections to outline.
        return detection_view(sid, room_id, task_id.split(":")[1:])

    try:
        for start in range(0, len(entries), 10):
            batch = dict(entries[start:start + 10])
            proposals.extend(run_review(scan_directory(sid), outline, y // size, size, batch, settings,
                                        render_task=render_task))
    except Exception as exc:
        raise HTTPException(502, "Deep Agents could not finish this review. Check the model configuration and try again.") from exc
    if not proposals:
        raise HTTPException(502, "The agent produced no proposals backed by the room photos.")
    with review_lock:
        details, _, current = room_review_context(sid, room_id)
        if current != revision:
            raise HTTPException(409, "Room evidence or review decisions changed. Run the review again.")
        saved = room_reviews(sid)
        review = saved.setdefault(room_id, {})
        applied = apply_automatic_object_decisions(details, review, object_decisions(sid, room_id), proposals)
        if applied:
            write_json(scan_directory(sid) / "room_reviews.json", saved)
        details, remaining, revision = room_review_context(sid, room_id)
    return {"revision": revision, "model": settings.identifier,
            "applied": applied, "details": details if applied else None,
            "proposals": [item for item in proposals if item not in applied and item.target in remaining],
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

    view = detection_view(sid, room_id, [detection_id(hit) for hit in hits])
    try:
        result = suggest_match(view, hits, settings)
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
    try:
        metrics = room_acoustics(room, scenario)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {**scenario, **metrics}


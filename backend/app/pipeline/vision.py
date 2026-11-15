"""Optional local YOLO evidence from Matterport room images and Vexcel aerials."""
import argparse
import json
import logging
import os
from functools import lru_cache
from importlib.util import find_spec

from PIL import Image

from app.pipeline.cache_files import write_json
from app.sources.config import DATA, ROOT

MODEL = "yolov8s-worldv2.pt"
# Each label YOLO-World looks for, with the text descriptions it matches against. One word is often not enough:
# with only "door", plain white panel doors came back as "cabinet" (1 door against 177 cabinets in four scans).
# Bathroom and kitchen fixtures are listed too; without them YOLO-World calls a bathtub a "bed".
ROOM_PROMPTS = {
    "chair": ["chair"], "sofa": ["sofa"], "table": ["table"], "desk": ["desk"], "bed": ["bed"],
    "bookshelf": ["bookshelf"], "cabinet": ["kitchen cabinet", "cabinet", "row of kitchen cabinets", "built-in cabinetry", "upper cabinets"], "rug": ["rug", "area rug", "rug on the floor"],
    "window": ["window", "glass window", "window with blinds"],
    "curtain": ["curtain", "drapes"],
    "door": ["door", "interior door", "white panel door", "closet door", "open door", "doorway"],
    "fireplace": ["fireplace", "brick fireplace"],
    "air conditioner": ["air conditioner", "portable air conditioner", "window air conditioner"],
    "toilet": ["toilet"], "bathtub": ["bathtub"], "shower": ["shower"], "sink": ["sink"],
    "refrigerator": ["refrigerator"], "stove": ["stove"],
}
# Look-alikes YOLO-World otherwise calls a fireplace (framed pictures) or an air conditioner (vents). Matching boxes
# compete with the real labels and are then dropped, so they never reach the room's evidence.
# Fluorescent panels and door bottoms were the usual "bathtubs".
DECOY_PROMPTS = ["picture frame", "painting", "air vent", "floor vent", "ceiling light", "fluorescent ceiling light",
                 "recessed light panel", "light fixture", "door threshold",
                 "checkered tile floor", "tile floor"]       # tile floors were the usual false "rugs"
ROOM_CLASSES = tuple(ROOM_PROMPTS)
DECOY = "decoy"
# Labels too unreliable to trust at any score (framed pictures and dark doorways outscore real fireplaces),
# so they are always listed as candidates for a person or the review agent to check.
ALWAYS_REVIEW = {"fireplace"}
# Things that cannot appear in the straight-up ceiling view (light panels there often look like tubs or beds).
NOT_ON_CEILING = {"bathtub", "toilet", "bed", "sofa", "chair", "table", "desk", "rug", "sink", "stove", "refrigerator",
                  "bookshelf", "fireplace", "window"}
# Describe what the top-down camera sees; "building" alone misses roofs in our Vexcel clips.
AERIAL_CLASSES = ("house roof", "building roof", "commercial roof")
MIN_SCORE = 0.10
REVIEW_BELOW = 0.30
# Soft furnishings decide how much sound a room absorbs, and YOLO-World scores them low, so they are accepted at a
# lower score. The view rules below keep the extra detections plausible.
LABEL_REVIEW_BELOW = {"rug": 0.18, "curtain": 0.18, "sofa": 0.18, "bed": 0.18, "bookshelf": 0.18, "window": 0.20}
# In a wall view these must be near the camera: small boxes are usually seen through a doorway, in another room.
NEAR_LABELS = {"rug", "sofa", "bed", "toilet", "bathtub", "sink"}
NEAR_MIN_AREA = 0.008                          # share of the view a nearby rug, sofa or bed covers at least
FULL_FACE_IMGSZ = 960         # detect on the full 2048 px panorama faces, not the 200 px sheet thumbnails
VIEWS = ("Ceiling", "Floor", "Wall 1", "Wall 2", "Wall 3", "Wall 4")
FACE_ORDER = (0, 5, 1, 2, 3, 4)
SHEET_MARGIN = 70
MODEL_DIR = ROOT / ".vision-cache"
logger = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def detector(classes):
    os.environ.setdefault("YOLO_CONFIG_DIR", str(MODEL_DIR / "config"))
    os.environ.setdefault("MPLCONFIGDIR", str(MODEL_DIR / "matplotlib"))
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    from ultralytics import YOLOWorld
    from ultralytics.nn import text_model
    from ultralytics.utils.downloads import safe_download

    # Keep the CLIP download alongside the YOLO weights, outside served scan data.
    text_model.WEIGHTS_DIR = MODEL_DIR
    weights = MODEL_DIR / MODEL
    if not weights.exists():
        MODEL_DIR.mkdir(exist_ok=True)
        safe_download(
            f"https://github.com/ultralytics/assets/releases/download/v8.3.0/{MODEL}",
            file=weights, min_bytes=1_000_000, progress=False,
        )
    model = YOLOWorld(str(weights))
    model.set_classes(list(classes))
    return model


def predict(images, classes, imgsz):
    """Convert Ultralytics tensors to ordinary values, retaining input-image coordinates.

    `classes` is a tuple of labels, or a dict of label -> text descriptions (see ROOM_PROMPTS). Overlapping boxes
    compete across labels, so one object gets the single best-matching label instead of "door" and "cabinet"."""
    pairs = ([(prompt, label) for label, prompts in classes.items() for prompt in prompts]
             if isinstance(classes, dict) else [(label, label) for label in classes])
    results = detector(tuple(prompt for prompt, _ in pairs)).predict(
        images, imgsz=imgsz, conf=MIN_SCORE, iou=0.45, max_det=100,
        device="cpu", verbose=False, agnostic_nms=True,
    )
    return [
        [
            {"label": pairs[int(label)][1], "confidence": round(score, 3),
             "needs_review": score < REVIEW_BELOW, "box_px": [round(n, 1) for n in coords]}
            for label, score, coords in zip(
                result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xyxy.tolist()
            )
        ]
        for result in results
    ]


def inspect_rooms(directory, rooms, report):
    sheet_path = directory / "room_sheet.jpg"
    if not sheet_path.is_file() or not rooms:
        return {"status": "unavailable", "rooms": {}}
    by_room = {}
    sky_cache = {}
    faces_by_room = {}
    names = room_names(directory)
    with Image.open(sheet_path) as sheet:
        width, height = sheet.size
        size = height // len(rooms)
        if not size or height != size * len(rooms) or width != SHEET_MARGIN + size * len(VIEWS):
            raise ValueError("Room sheet does not match the cached room layout.")
        for row, room in enumerate(rooms):
            if not room.get("panorama_available", True):
                by_room[room["id"]] = {"status": "unavailable", "objects": [], "candidates": []}
                continue
            report(f"Detecting objects in room {row + 1} of {len(rooms)}")
            bounds = [(SHEET_MARGIN + col * size, row * size,
                       SHEET_MARGIN + (col + 1) * size, (row + 1) * size) for col in range(len(VIEWS))]
            detections = []
            faces = full_faces(directory, room, sky_cache)
            faces_by_room[room["id"]] = faces
            prompts = {**ROOM_PROMPTS, DECOY: DECOY_PROMPTS}
            if faces:
                found = predict(faces, prompts, FULL_FACE_IMGSZ)
                scale = size / faces[0].width        # boxes go back to sheet-thumbnail coordinates
                found = [[{**hit, "box_px": [round(n * scale, 1) for n in hit["box_px"]]} for hit in hits]
                         for hits in found]
            else:
                found = predict([sheet.crop(box) for box in bounds], prompts, 480)
            for view_index, hits in enumerate(found):
                x, y = bounds[view_index][:2]
                for hit in hits:
                    if hit["label"] == DECOY or not plausible(hit, VIEWS[view_index], size):
                        continue
                    if hit["label"] in LABEL_REVIEW_BELOW:
                        hit = {**hit, "needs_review": hit["confidence"] < LABEL_REVIEW_BELOW[hit["label"]]}
                    # Saved labels win; on a first run Matterport's own room label is the name we have.
                    name = (names.get(room["id"]) or room.get("matterport_label") or "").lower()
                    if hit["label"] in BATH_FIXTURES and name and not any(word in name for word in BATH_WORDS):
                        hit = {**hit, "needs_review": True}     # a toilet in an office is usually a bin or chair
                    if hit["label"] in ALWAYS_REVIEW:
                        hit = {**hit, "needs_review": True}
                    left, top, right, bottom = hit["box_px"]
                    detections.append({
                        **hit, "view": VIEWS[view_index], "face_index": FACE_ORDER[view_index],
                        "panorama_id": room.get("sheet_panorama_id"),
                        "sheet_box_px": [x + left, y + top, x + right, y + bottom],
                    })
            detections = merge_runs(detections, size)
            for hit in detections:
                l, t, r, b = hit["box_px"]
                # A "cabinet" filling most of a view is usually wood paneling or a closet wall, not cabinetry.
                if hit["label"] in RUN_LABELS and (r - l) * (b - t) > 0.6 * size * size:
                    hit["needs_review"] = True
            detections.sort(key=lambda hit: -hit["confidence"])
            # A chair visible across two faces is evidence in two views, not two chairs.
            labels = sorted({hit["label"] for hit in detections if not hit["needs_review"]})
            candidates = sorted({hit["label"] for hit in detections if hit["needs_review"]} - set(labels))
            by_room[room["id"]] = {
                "status": "complete", "objects": labels, "candidates": candidates, "detections": detections,
                "wall_coverage": wall_coverage(detections, size),
                "floor_coverage": floor_coverage(detections, size),
            }
    from app.sources.review_model import resolve_review_model

    settings, _ = resolve_review_model()
    checked = 0
    if settings:
        checked = confirm_candidates(by_room, faces_by_room, size, settings, report)
        for room in by_room.values():
            if room.get("detections"):
                room["wall_coverage"] = wall_coverage(room["detections"], size)
                room["floor_coverage"] = floor_coverage(room["detections"], size)
    return {"status": "complete" if any(r["status"] == "complete" for r in by_room.values()) else "unavailable",
            "source": "room_sheet.jpg", "width": width, "height": height, "rooms": by_room,
            "candidates_checked": checked, "checked_by": settings.identifier if settings else None}


RUN_LABELS = ("cabinet", "bookshelf")      # pieces of one run of cabinetry or shelving merge into one object
COVERAGE_LABELS = ("cabinet", "bookshelf", "curtain", "window")


def full_faces(directory, room, sky_cache):
    """The room's six original panorama faces (cached under room_photos), or None if they cannot be fetched."""
    from app.pipeline.panoramas import download_face, face_path, save_face, skyboxes

    images = []
    for face_index in FACE_ORDER:
        path = face_path(directory, room, face_index)
        if not path.is_file():
            if "sky" not in sky_cache:
                try:
                    sky_cache["sky"] = skyboxes(directory.name)
                except BaseException:            # Matterport unavailable: fall back to the sheet
                    sky_cache["sky"] = {}
            pano = room.get("sheet_panorama_id") or (room.get("panos") or [None])[0]
            faces = sky_cache["sky"].get(pano) or []
            if len(faces) != 6:
                return None
            try:
                image, jpeg = download_face(faces[face_index])
            except Exception:
                return None
            save_face(path, image, jpeg)
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    return images


BATH_FIXTURES = {"toilet", "bathtub", "shower"}
BATH_WORDS = ("bath", "restroom", "toilet", "washroom", "powder", "wc", "lavatory", "shower")


def room_names(directory):
    """Room names from the saved labels, when the scan has been labelled."""
    path = directory / "materials.json"
    if not path.is_file():
        return {}
    return {room_id: (labels.get("type") or "") for room_id, labels in json.loads(path.read_text())["rooms"].items()}


CONFIRM_LABELS = set(LABEL_REVIEW_BELOW)       # low-score detections of these are checked by the vision model
CONFIRM_BATCH = 16


def confirm_candidates(by_room, faces_by_room, size, settings, report):
    """Ask the vision model whether each low-score rug, sofa, bed, curtain, shelf or window is really there.

    Each candidate is cropped from the full panorama face with some context and numbered. Confirmed ones become
    accepted detections marked "confirmed_by"; rejected ones stay low-score for a person to see."""
    import base64
    from io import BytesIO

    from langchain_core.messages import HumanMessage
    from pydantic import BaseModel, Field

    class Answer(BaseModel):
        present: list[bool] = Field(description="One entry per numbered crop, in order: is the named object "
                                                 "clearly inside the red box?")

    queue = []
    for room_id, room in by_room.items():
        faces = faces_by_room.get(room_id)
        if not faces:
            continue
        for hit in room.get("detections", []):
            if hit["label"] in CONFIRM_LABELS and hit["needs_review"]:
                queue.append((room_id, hit))
    model = settings.structured(Answer, max_tokens=400)
    for start in range(0, len(queue), CONFIRM_BATCH):
        batch = queue[start:start + CONFIRM_BATCH]
        report(f"Checking {start + len(batch)} of {len(queue)} uncertain soft furnishings and windows")
        content = [{"type": "text", "text": "Each image is a crop from a photo taken inside one room, with a red box. "
                    "For each crop, answer true only if the named object is clearly inside the red box AND belongs to "
                    "the room the camera is in. Answer false for anything seen through a doorway or opening into "
                    "another room, for reflections and pictures, and for tiled or checkered floor patterns (those are "
                    "not rugs). Answer in order. Objects: "
                    + "; ".join(f"{i + 1}: {hit['label']}" for i, (_, hit) in enumerate(batch))}]
        for room_id, hit in batch:
            face = faces_by_room[room_id][VIEWS.index(hit["view"])]
            k = face.width / size
            l, t, r, b = [n * k for n in hit["box_px"]]
            pad = 0.6 * max(r - l, b - t)
            crop = face.crop((max(0, l - pad), max(0, t - pad), min(face.width, r + pad), min(face.height, b + pad))).copy()
            from PIL import ImageDraw

            ImageDraw.Draw(crop).rectangle((l - max(0, l - pad), t - max(0, t - pad), r - max(0, l - pad),
                                            b - max(0, t - pad)), outline=(255, 0, 0), width=max(3, crop.width // 120))
            crop.thumbnail((384, 384))
            buffer = BytesIO()
            crop.save(buffer, format="JPEG", quality=85)
            content.append({"type": "image", "mime_type": "image/jpeg",
                            "base64": base64.b64encode(buffer.getvalue()).decode("ascii")})
        try:
            answer = model.invoke([HumanMessage(content=content)])
        except Exception:
            logger.warning("Candidate check failed for a batch", exc_info=True)
            continue
        if not answer or len(answer.present) != len(batch):
            continue
        for (room_id, hit), present in zip(batch, answer.present):
            if present:
                hit["needs_review"] = False
                hit["confirmed_by"] = settings.identifier
    for room in by_room.values():
        hits = room.get("detections", [])
        room["objects"] = sorted({hit["label"] for hit in hits if not hit["needs_review"]})
        room["candidates"] = sorted({hit["label"] for hit in hits if hit["needs_review"]} - set(room["objects"]))
    return len(queue)


def plausible(hit, view, size):
    """Drop detections in places the object cannot be."""
    if view == "Ceiling" and hit["label"] in NOT_ON_CEILING:
        return False
    l, t, r, b = hit["box_px"]
    if hit["label"] == "rug" and view != "Floor" and b < 0.55 * size:
        return False                              # a rug in a wall view must reach the lower part of the picture
    if hit["label"] in NEAR_LABELS and view != "Floor" and (r - l) * (b - t) < NEAR_MIN_AREA * size * size:
        return False                              # small and far away: seen through a doorway, in another room
    return True


def merge_runs(hits, size):
    """Join boxes of one label that touch side by side in the same view into a single run.

    YOLO-World usually finds a wall of cabinets one door at a time; for the room inventory and for how much wall
    the cabinetry covers, the run is the object. Boxes join when they overlap vertically by half and the gap
    between them is under 6% of the view width."""
    out, gap = [], 0.06 * size
    groups = {}
    for hit in hits:
        if hit["label"] in RUN_LABELS and not hit["needs_review"]:
            groups.setdefault((hit["view"], hit["label"]), []).append(hit)
        else:
            out.append(hit)
    for (view, label), items in groups.items():
        runs = []
        for hit in sorted(items, key=lambda h: h["box_px"][0]):
            l, t, r, b = hit["box_px"]
            for run in runs:
                rl, rt, rr, rb = run["box_px"]
                vertical = min(b, rb) - max(t, rt)
                if vertical > 0.5 * min(b - t, rb - rt) and l - rr < gap and rl - r < gap:
                    run["box_px"] = [min(l, rl), min(t, rt), max(r, rr), max(b, rb)]
                    run["parts"] += 1
                    run["confidence"] = max(run["confidence"], hit["confidence"])
                    sx, sy = run["sheet_box_px"][0] - rl, run["sheet_box_px"][1] - rt
                    run["sheet_box_px"] = [run["box_px"][0] + sx, run["box_px"][1] + sy,
                                           run["box_px"][2] + sx, run["box_px"][3] + sy]
                    break
            else:
                runs.append({**hit, "box_px": list(hit["box_px"]), "sheet_box_px": list(hit["sheet_box_px"]),
                             "parts": 1})
        out.extend(runs)
    return out


def wall_coverage(hits, size, grid=40):
    """Share of the four wall views covered by each label (union of boxes, so overlaps count once)."""
    cell = size / grid
    coverage = {}
    for label in COVERAGE_LABELS:
        covered = 0
        for view in ("Wall 1", "Wall 2", "Wall 3", "Wall 4"):
            boxes = [h["box_px"] for h in hits if h["label"] == label and h["view"] == view and not h["needs_review"]]
            if not boxes:
                continue
            covered += sum(any(l <= (i + 0.5) * cell <= r and t <= (j + 0.5) * cell <= b for l, t, r, b in boxes)
                           for i in range(grid) for j in range(grid))
        coverage[label] = round(covered / (4 * grid * grid), 3)
    return coverage


def floor_coverage(hits, size, grid=40):
    """Share of the straight-down floor view under a rug, and whether a rug was seen at all. The echo step turns a
    rug seen only from the side into a typical share for the room type."""
    rugs = [h for h in hits if h["label"] == "rug" and not h["needs_review"]]
    if not rugs:
        return {}
    cell = size / grid
    boxes = [h["box_px"] for h in rugs if h["view"] == "Floor"]
    measured = sum(any(l <= (i + 0.5) * cell <= r and t <= (j + 0.5) * cell <= b for l, t, r, b in boxes)
                   for i in range(grid) for j in range(grid)) / (grid * grid)
    return {"rug": round(measured, 3), "rug_seen": True}


def tiles(width, height, size=800, overlap=200):
    def starts(length):
        last = max(0, length - size)
        return sorted(set(range(0, last, size - overlap)) | {last})

    for y in starts(height):
        for x in starts(width):
            yield x, y, min(width, x + size), min(height, y + size)


def suppress_duplicates(hits):
    """Discard boxes for the same roof found in more than one overlapping tile."""
    def overlaps(a, b):
        inter = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
        area_a, area_b = [(box[2] - box[0]) * (box[3] - box[1]) for box in (a, b)]
        return inter > 0.45 * (area_a + area_b - inter) or inter > 0.85 * min(area_a, area_b)

    kept = []
    for hit in sorted(hits, key=lambda hit: -hit["confidence"]):
        if not any(overlaps(hit["box_px"], other["box_px"]) for other in kept):
            kept.append(hit)
    return kept


def inspect_aerial(directory, report):
    source = directory / "ortho.png"
    if not source.is_file():
        return {"status": "unavailable"}
    hits = []
    report("Detecting nearby buildings in the Vexcel aerial image")
    with Image.open(source) as image:
        width, height = image.size
        windows = list(tiles(width, height))
        for start in range(0, len(windows), 4):
            batch = windows[start:start + 4]
            for (x, y, _, _), predictions in zip(batch, predict([image.crop(box) for box in batch], AERIAL_CLASSES, 800)):
                for hit in predictions:
                    left, top, right, bottom = hit["box_px"]
                    hits.append({**hit, "box_px": [x + left, y + top, x + right, y + bottom]})
    return {"status": "complete", "source": source.name, "width": width, "height": height,
            "detections": suppress_duplicates(hits)}


def analyse_vision(directory, geometry, report, *, refresh=False, strict=False):
    """Reuse successful passes and allow echo analysis when optional vision is unavailable."""
    path = directory / "vision.json"
    cache = json.loads(path.read_text()) if path.is_file() and not refresh else {}
    result = {"model": MODEL, "minimum_score": MIN_SCORE, "review_below": REVIEW_BELOW}
    same_model = all(cache.get(field) == value for field, value in result.items())
    for key, filename, classes, run in (
        ("indoor", "room_sheet.jpg", {**ROOM_PROMPTS, DECOY: DECOY_PROMPTS, "_not_on_ceiling": sorted(NOT_ON_CEILING), "_runs": list(RUN_LABELS),
                                         "_full_faces": FULL_FACE_IMGSZ, "_thresholds": LABEL_REVIEW_BELOW, "_near": NEAR_MIN_AREA}, lambda: inspect_rooms(directory, geometry["rooms"], report)),
        ("aerial", "ortho.png", AERIAL_CLASSES, lambda: inspect_aerial(directory, report)),
    ):
        source = directory / filename
        source_stamp = source.stat().st_mtime_ns if source.is_file() else None
        signature = {"classes": classes if isinstance(classes, dict) else list(classes), "mtime_ns": source_stamp}
        saved = cache.get(key, {})
        if same_model and saved.get("status") == "complete" and saved.get("signature") == signature and (
            key != "indoor" or saved["rooms"].keys() == {room["id"] for room in geometry["rooms"]}
        ):
            result[key] = saved
            continue
        if source_stamp is not None and not all(find_spec(name) for name in ("ultralytics", "clip")):
            if strict:
                raise RuntimeError("Install the packages in backend/requirements-vision.txt to use YOLO.")
            report("YOLO is not installed. Continuing with the available data.")
            result[key] = {"status": "failed"}
            continue
        try:
            result[key] = {**run(), "signature": signature}
        except Exception:
            if strict:
                raise
            logger.exception("Optional YOLO %s pass failed for %s", key, directory.name)
            result[key] = {"status": "failed"}
            report(f"YOLO {key} pass could not run. Continuing with the available data.")
    if result != cache:
        write_json(path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="Matterport scan ID with cached rooms.json")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if not args.model.isascii() or not args.model.isalnum():
        parser.error("invalid Matterport scan ID")
    directory = DATA / args.model
    geometry = json.loads((directory / "rooms.json").read_text())
    result = analyse_vision(directory, geometry, print, refresh=args.refresh, strict=True)
    print(f"{directory / 'vision.json'}: rooms {result['indoor']['status']}, aerial {result['aerial']['status']}")


if __name__ == "__main__":
    main()

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
ROOM_CLASSES = ("chair", "sofa", "table", "desk", "bed", "bookshelf", "cabinet", "rug", "window", "curtain", "door")
# Describe what the top-down camera sees; "building" alone misses roofs in our Vexcel clips.
AERIAL_CLASSES = ("house roof", "building roof", "commercial roof")
MIN_SCORE = 0.10
REVIEW_BELOW = 0.30
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
    """Convert Ultralytics tensors to ordinary values, retaining input-image coordinates."""
    results = detector(classes).predict(
        images, imgsz=imgsz, conf=MIN_SCORE, iou=0.45, max_det=100,
        device="cpu", verbose=False,
    )
    return [
        [
            {"label": classes[int(label)], "confidence": round(score, 3),
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
            for view_index, hits in enumerate(predict([sheet.crop(box) for box in bounds], ROOM_CLASSES, 480)):
                x, y = bounds[view_index][:2]
                for hit in hits:
                    left, top, right, bottom = hit["box_px"]
                    detections.append({
                        **hit, "view": VIEWS[view_index], "face_index": FACE_ORDER[view_index],
                        "panorama_id": room.get("sheet_panorama_id"),
                        "sheet_box_px": [x + left, y + top, x + right, y + bottom],
                    })
            detections.sort(key=lambda hit: -hit["confidence"])
            # A chair visible across two faces is evidence in two views, not two chairs.
            labels = sorted({hit["label"] for hit in detections if not hit["needs_review"]})
            candidates = sorted({hit["label"] for hit in detections if hit["needs_review"]} - set(labels))
            by_room[room["id"]] = {
                "status": "complete", "objects": labels, "candidates": candidates, "detections": detections,
            }
    return {"status": "complete" if any(r["status"] == "complete" for r in by_room.values()) else "unavailable",
            "source": "room_sheet.jpg", "width": width, "height": height, "rooms": by_room}


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
        ("indoor", "room_sheet.jpg", ROOM_CLASSES, lambda: inspect_rooms(directory, geometry["rooms"], report)),
        ("aerial", "ortho.png", AERIAL_CLASSES, lambda: inspect_aerial(directory, report)),
    ):
        source = directory / filename
        source_stamp = source.stat().st_mtime_ns if source.is_file() else None
        signature = {"classes": list(classes), "mtime_ns": source_stamp}
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

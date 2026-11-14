"""Group YOLO detections across the six faces of one Matterport panorama."""
from hashlib import sha256
from itertools import combinations
import json

# Directions match matterport.equirect(). Each tuple lists the image's
# top-left, top-right, bottom-left and bottom-right corner on the cube.
CORNERS = (
    ((-1, 1, -1), (1, 1, -1), (-1, 1, 1), (1, 1, 1)),
    ((-1, 1, 1), (1, 1, 1), (-1, -1, 1), (1, -1, 1)),
    ((1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1)),
    ((1, 1, -1), (-1, 1, -1), (1, -1, -1), (-1, -1, -1)),
    ((-1, 1, -1), (-1, 1, 1), (-1, -1, -1), (-1, -1, 1)),
    ((-1, -1, 1), (1, -1, 1), (-1, -1, -1), (1, -1, -1)),
)
EDGES = ((0, 2), (1, 3), (0, 1), (2, 3))  # left, right, top, bottom
SEAMS = {}
for first, second in combinations(range(len(CORNERS)), 2):
    for a, (a0, a1) in enumerate(EDGES):
        start, end = CORNERS[first][a0], CORNERS[first][a1]
        for b, (b0, b1) in enumerate(EDGES):
            other_start, other_end = CORNERS[second][b0], CORNERS[second][b1]
            if {start, end} == {other_start, other_end}:
                SEAMS[first, second] = a, b, start != other_start


def detection_id(hit):
    identity = [hit.get("panorama_id"), hit["face_index"], hit.get("original_label", hit["label"]), hit["box_px"]]
    return sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()[:24]


def edge_interval(hit, edge, size):
    left, top, right, bottom = (value / size for value in hit["box_px"])
    if edge < 2:
        return (left if edge == 0 else 1 - right), (top, bottom)
    return (top if edge == 2 else 1 - bottom), (left, right)


def overlap_ratio(a, b):
    intersection = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    span = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / span if span else 0


def box_overlap(first, second):
    a, b = first["box_px"], second["box_px"]
    shared_width = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    shared_height = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = shared_width * shared_height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0


def containment(first, second):
    """Share of the smaller box that lies inside the larger one."""
    a, b = first["box_px"], second["box_px"]
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return intersection / smaller if smaller else 0


# YOLO-World often gives one object two related labels; these count as the same kind of object.
FAMILIES = {"sofa": "seating", "chair": "seating", "table": "surface", "desk": "surface",
            "cabinet": "storage", "bookshelf": "storage", "window": "opening", "curtain": "opening"}


def family(label):
    return FAMILIES.get(label, label)


def seam_fit(a, b, size):
    """(gap, overlap) where two boxes on adjacent faces meet at their shared panorama edge, else None."""
    faces = a["face_index"], b["face_index"]
    if faces not in SEAMS:
        return None
    edge_a, edge_b, reversed_edge = SEAMS[faces]
    gap_a, span_a = edge_interval(a, edge_a, size)
    gap_b, span_b = edge_interval(b, edge_b, size)
    if reversed_edge:
        span_b = 1 - span_b[1], 1 - span_b[0]
    return max(gap_a, gap_b), overlap_ratio(span_a, span_b)


def candidate_pairs(hits, size):
    """Pairs of detections that may show one physical object: {pair: (kind, strong, strength, reason)}."""
    pairs = {}
    for first, second in combinations(hits, 2):
        a, b = hits[first], hits[second]
        if a.get("panorama_id") != b.get("panorama_id"):
            continue
        pair = tuple(sorted((first, second)))
        related = family(a["label"]) == family(b["label"])
        if a["face_index"] == b["face_index"]:
            iou, inside = box_overlap(a, b), containment(a, b)
            if iou >= 0.85:
                reason = "the same box with two labels" if a["label"] != b["label"] else "overlapping boxes in one view"
                pairs[pair] = ("face", True, iou, reason)
            elif related and (iou >= 0.5 or inside >= 0.85):
                pairs[pair] = ("face", True, max(iou, inside), "a smaller box inside a larger one")
            elif iou >= 0.5:
                pairs[pair] = ("face", False, iou, "overlapping boxes with different labels")
            continue
        if not related:
            continue
        if a["face_index"] > b["face_index"]:
            a, b = b, a
        fit = seam_fit(a, b, size)
        if fit is None:
            continue
        gap, overlap = fit
        if gap > 0.06 or overlap < 0.35:
            continue
        pairs[pair] = ("seam", gap <= 0.04 and overlap >= 0.6, overlap, "the boxes meet where two views join")
    return pairs


def group_detections(raw_hits, size, decisions):
    """Group detections that show one physical object, and list the pairs a person should check.

    1. Saved decisions win: "same" always joins two boxes, "separate" never lets them join.
    2. Within one view, a box nested inside another (or the same box with two labels) is one object.
    3. Across a seam between two views, boxes that meet edge to edge join when that is the only
       candidate on each side and at least one box has a confident score.
    Everything else that could be the same object becomes a review. Groups are evidence, not a verified count.
    """
    hits = {detection_id(hit): hit for hit in raw_hits}
    order = {key: index for index, key in enumerate(hits)}
    saved = {tuple(sorted(key.split(":"))): value for key, value in decisions.items()}
    saved = {pair: value for pair, value in saved.items() if len(pair) == 2 and all(i in hits for i in pair)}
    pairs = candidate_pairs(hits, size)
    separate = {frozenset(pair) for pair, value in saved.items() if value == "separate"}
    groups = {key: frozenset((key,)) for key in hits}

    def faces(group):
        return {hits[key]["face_index"] for key in group}

    def merge(first, second):
        left, right = groups[first], groups[second]
        if left == right:
            return True
        if any(frozenset((a, b)) in separate for a in left for b in right):
            return False
        combined = left | right
        for key in combined:
            groups[key] = combined
        return True

    for pair, value in saved.items():
        if value == "same" and not merge(*pair):
            raise ValueError("That decision conflicts with an existing object match. Undo the other decision first.")

    # Same-view duplicates first, so each object is one group before matching across views.
    for pair, (kind, strong, _, _) in sorted(pairs.items(), key=lambda item: -item[1][2]):
        if kind == "face" and strong and pair not in saved:
            merge(*pair)

    # Across a seam, merge only when each group has exactly one candidate group on the other view.
    seam = [(pair, value) for pair, value in pairs.items() if value[0] == "seam" and saved.get(pair) != "separate"]
    partners = {}
    for (first, second), _ in seam:
        for mine, theirs in ((first, second), (second, first)):
            partners.setdefault((groups[mine], hits[theirs]["face_index"]), set()).add(groups[theirs])
    for pair, (_, strong, _, _) in sorted(seam, key=lambda item: -item[1][2]):
        first, second = pair
        left, right = groups[first], groups[second]
        if not strong or pair in saved or left == right or faces(left) & faces(right):
            continue
        unique = (len(partners.get((left, hits[second]["face_index"]), ())) == 1 and
                  len(partners.get((right, hits[first]["face_index"]), ())) == 1)
        if unique and not all(hits[key]["needs_review"] for key in left | right):
            merge(*pair)

    # One review per pair of groups; skip pairs where both sides are only low-score boxes.
    reviews, seen = [], set()
    for pair in sorted(pairs.keys() | saved.keys(), key=lambda p: (saved.get(p) is None, -pairs.get(p, ("", False, 0))[2])):
        first, second = pair
        decision = saved.get(pair)
        key = frozenset((groups[first], groups[second]))
        if decision is None:
            if groups[first] == groups[second] or key in seen:
                continue
            if all(hits[i]["needs_review"] for i in groups[first] | groups[second]):
                continue
        seen.add(key)
        reviews.append({"id": ":".join(pair), "detection_ids": pair, "decision": decision,
                        "reason": pairs[pair][3] if pair in pairs else "saved decision"})

    pending = {key for review in reviews if review["decision"] is None
               for group in (groups[review["detection_ids"][0]], groups[review["detection_ids"][1]]) for key in group}
    result = []
    for keys in set(groups.values()):
        ordered = sorted(keys, key=order.get)
        # Name the group after its most confident box.
        lead = max(ordered, key=lambda key: hits[key]["confidence"])
        result.append({"id": ordered[0], "label": hits[lead]["label"], "detection_ids": ordered,
                       "views": sorted({hits[key]["view"] for key in keys if "view" in hits[key]}),
                       "confidence": max(hits[key]["confidence"] for key in keys),
                       "status": "needs_match" if pending & keys else
                       "low_score" if all(hits[key]["needs_review"] for key in keys) else "estimated"})
    reviews.sort(key=lambda review: review["decision"] is not None)
    result.sort(key=lambda group: (group["status"] == "low_score", -group["confidence"], order[group["id"]]))
    return {"groups": result, "reviews": reviews}


def merge_decisions(raw_hits, size, decisions, detection_ids):
    """Decisions that join all the given detections into one object (dropping any "separate" among them)."""
    ids = list(dict.fromkeys(detection_ids))
    chosen = set(ids)
    updated = {key: value for key, value in decisions.items()
               if not (value == "separate" and set(key.split(":")) <= chosen)}
    for other in ids[1:]:
        updated[":".join(sorted((ids[0], other)))] = "same"
    group_detections(raw_hits, size, updated)          # raises ValueError on a conflict
    return updated


def split_decisions(raw_hits, size, decisions, detection_ids):
    """Decisions that keep each of the given detections as its own object."""
    chosen = set(detection_ids)
    updated = {key: value for key, value in decisions.items()
               if not (value == "same" and set(key.split(":")) <= chosen)}
    for first, second in combinations(sorted(chosen), 2):
        updated[f"{first}:{second}"] = "separate"
    group_detections(raw_hits, size, updated)
    return updated

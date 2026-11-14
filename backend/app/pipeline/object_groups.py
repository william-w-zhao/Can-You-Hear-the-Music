"""Group YOLO detections across the six faces of one Matterport panorama."""
from collections import Counter
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


def group_detections(raw_hits, size, decisions):
    """Return evidence groups and unresolved pairs without treating them as a verified count."""
    hits = {detection_id(hit): hit for hit in raw_hits}
    saved = {tuple(key.split(":")): value for key, value in decisions.items()}
    saved = {pair: value for pair, value in saved.items() if len(pair) == 2 and all(i in hits for i in pair)}
    pairs = {}
    competition = Counter()
    for first, second in combinations(hits, 2):
        a, b = hits[first], hits[second]
        pair = tuple(sorted((first, second)))
        if a.get("panorama_id") != b.get("panorama_id"):
            continue
        if a["face_index"] > b["face_index"]:
            first, second, a, b = second, first, b, a
        faces = a["face_index"], b["face_index"]
        if faces[0] == faces[1]:
            if box_overlap(a, b) >= 0.80:
                pairs[pair] = (False, None, "overlapping boxes in one view")
            continue
        if a["label"] != b["label"] or faces not in SEAMS:
            continue
        edge_a, edge_b, reversed_edge = SEAMS[faces]
        gap_a, span_a = edge_interval(a, edge_a, size)
        gap_b, span_b = edge_interval(b, edge_b, size)
        if reversed_edge:
            span_b = 1 - span_b[1], 1 - span_b[0]
        overlap = overlap_ratio(span_a, span_b)
        if max(gap_a, gap_b) > 0.06 or overlap < 0.35:
            continue
        keys = ((first, faces[1]), (second, faces[0]))
        if saved.get(pair) != "separate":
            competition.update(keys)
        strong = max(gap_a, gap_b) <= 0.025 and overlap >= 0.70 and not (a["needs_review"] or b["needs_review"])
        pairs[pair] = (strong, keys, "boxes meet at a panorama edge")

    separate = {frozenset(pair) for pair, value in saved.items() if value == "separate"}
    groups = {key: {key} for key in hits}

    def merge(first, second, automatic=False):
        left, right = groups[first], groups[second]
        if left is right:
            return True
        if any(frozenset((a, b)) in separate for a in left for b in right):
            return False
        if automatic and {hits[i]["face_index"] for i in left} & {hits[i]["face_index"] for i in right}:
            return False
        combined = left | right
        for key in combined:
            groups[key] = combined
        return True

    for pair, value in saved.items():
        if value == "same" and not merge(*pair):
            raise ValueError("That decision conflicts with an existing object match. Undo the other decision first.")

    for pair, (strong, keys, _) in pairs.items():
        if pair not in saved and strong and all(competition[key] == 1 for key in keys):
            merge(*pair, automatic=True)

    reviews = []
    for pair in pairs.keys() | saved.keys():
        first, second = pair
        decision = saved.get(pair)
        if decision or groups[first] is not groups[second]:
            reviews.append({"id": ":".join(pair), "detection_ids": pair, "decision": decision,
                            "reason": pairs.get(pair, (None, None, "saved review"))[2]})

    pending = {key for review in reviews if review["decision"] is None for key in review["detection_ids"]}
    order = {key: index for index, key in enumerate(hits)}
    result = []
    for keys in {frozenset(group) for group in groups.values()}:
        lead = min(keys, key=order.get)
        ordered = sorted(keys, key=order.get)
        result.append({"id": lead, "label": hits[lead]["label"], "detection_ids": ordered,
                       "status": "needs_match" if pending & keys else
                       "low_score" if all(hits[key]["needs_review"] for key in keys) else "estimated"})
    reviews.sort(key=lambda review: (review["decision"] is not None, review["id"]))
    result.sort(key=lambda group: order[group["id"]])
    return {"groups": result, "reviews": reviews}

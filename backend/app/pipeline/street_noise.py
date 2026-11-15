"""Street noise for a whole scan: outdoors at the building and inside every analysed room, wall by wall."""
import json

from app.pipeline.facades import exterior_walls, orientation, place_walls
from app.pipeline.object_groups import detection_id, reviewed_hits
from app.pipeline.traffic_noise import ASSUMPTIONS, INDOOR_DNL_LIMIT, dnl, indoor, outdoor, wall_outdoor
from app.sources.config import DATA
from app.sources.traffic import fetch_traffic, metres


def room_walls(sid, traffic):
    """{room_id: [outside walls with hourly outdoor levels]} and a summary of how they were placed."""
    directory = DATA / sid
    geometry = json.loads((directory / "rooms.json").read_text())
    walls = weight_glass(exterior_walls(geometry), window_directions(sid, geometry))
    lat, lon = traffic["location"]["lat"], traffic["location"]["lon"]
    placement = orientation(geometry, directory, lat, lon)
    roads = traffic["roads"]
    roads_xy = [[[metres(lat, lon, a, b) for a, b in line] for line in road.get("lines", [])] for road in roads]
    if placement["status"] == "unknown" or not any(roads_xy):
        # No direction: every outside wall is assumed to face the traffic at the building's distance.
        outside = outdoor(traffic)["hourly_db"]
        levels = {room_id: [{**wall, "hourly_db": outside} for wall in items] for room_id, items in walls.items()}
        return levels, {"status": "unknown", "reason": placement.get("reason", "No road geometry.")}
    # Each possible placement gives every wall a level; keep the louder one per wall (the cautious answer).
    best = {}
    for option in placement["placements"]:
        placed = place_walls(walls, placement["plan_centre"], option, placement["footprint"])
        for room_id, items in placed.items():
            for wall in items:
                key = (room_id, wall["a"], wall["b"])
                levels = wall_outdoor(wall, roads_xy, roads)
                if key not in best or dnl(levels) > dnl(best[key]["hourly_db"]):
                    best[key] = {**wall, "hourly_db": levels}
    levels = {room_id: [] for room_id in walls}
    for (room_id, _, _), wall in best.items():
        levels[room_id].append(wall)
    summary = {"status": placement["status"], "fit": placement["fit"], "coverage": placement["coverage"],
               "options": len(placement["placements"])}
    return levels, summary


PANORAMA_HEADINGS = """query($id: ID!) { model(id: $id) { panoLocations { id rotation { x y z w } } } }"""
WALL_VIEWS = ("Wall 1", "Wall 2", "Wall 3", "Wall 4")
WINDOW_WEIGHT = 4.0      # an outside wall with a window seen on it takes this many times its share of the glass


def panorama_headings(sid):
    """Each panorama's heading in the floor-plan frame (radians), cached; Matterport stores it as a quaternion."""
    import math

    from app.sources.matterport import mp

    path = DATA / sid / "pano_headings.json"
    if path.is_file():
        return json.loads(path.read_text())
    headings = {loc["id"]: 2 * math.atan2(loc["rotation"]["z"], loc["rotation"]["w"])
                for loc in mp(PANORAMA_HEADINGS, id=sid)["model"]["panoLocations"] if loc.get("rotation")}
    path.write_text(json.dumps(headings))
    return headings


def window_directions(sid, geometry):
    """{room_id: [unit vectors in the floor-plan frame]} for windows seen in each room's wall views.

    The cube views run front, right, back, left from the panorama's heading. Checked against the scans: with this
    order 79% of detected windows land on a wall the floor plan says is outside (about 50% would be chance)."""
    import math

    directory = DATA / sid
    if not (directory / "vision.json").is_file():
        return {}
    try:
        headings = panorama_headings(sid)
    except BaseException:                        # the Matterport API is optional here
        return {}
    evidence = json.loads((directory / "vision.json").read_text()).get("indoor", {}).get("rooms", {})
    out = {}
    for room in geometry["rooms"]:
        pano = room.get("sheet_panorama_id") or (room.get("panos") or [None])[0]
        if pano not in headings:
            continue
        for hit in evidence.get(room["id"], {}).get("detections", []):
            if hit["label"] == "window" and hit.get("view") in WALL_VIEWS and not hit.get("needs_review"):
                angle = headings[pano] - WALL_VIEWS.index(hit["view"]) * math.pi / 2
                out.setdefault(room["id"], []).append((math.cos(angle), math.sin(angle)))
    return out


def weight_glass(walls, directions):
    """Give walls facing a seen window a larger share of the room's glass."""
    for room_id, items in walls.items():
        seen = directions.get(room_id, [])
        hits = [any(wall["normal"][0] * x + wall["normal"][1] * y > 0.7 for x, y in seen) for wall in items]
        if any(hits):
            for wall, hit in zip(items, hits):
                wall["glass_weight"] = wall["length_m"] * (WINDOW_WEIGHT if hit else 1.0)
                wall["window_seen"] = hit
    return walls


def rooms_with_window_detections(directory):
    """Rooms with a window detection accepted by the score threshold or a saved review."""
    vision = directory / "vision.json"
    if not vision.is_file():
        return set()
    reviews = directory / "room_reviews.json"
    reviewed = json.loads(reviews.read_text()) if reviews.is_file() else {}
    evidence = json.loads(vision.read_text()).get("indoor", {}).get("rooms", {})
    result = set()
    for room_id, room in evidence.items():
        review = reviewed.get(room_id, {})
        kept = set(review.get("kept", []))
        for hit in reviewed_hits(room.get("detections", []), review.get("labels", {})):
            if hit["label"].casefold() == "window" and (not hit.get("needs_review", True) or detection_id(hit) in kept):
                result.add(room_id)
                break
    return result


def build_report(sid, year=None, rooms=None, segment=None):
    """`rooms` maps room_id to the current room record (with reviewed materials)."""
    from app.pipeline.exterior import assess_exterior
    from app.sources.review_model import resolve_review_model

    traffic = fetch_traffic(sid)
    try:
        exterior = assess_exterior(sid, settings=resolve_review_model()[0], segment=segment, year=year)
    except (OSError, KeyError, ValueError):
        exterior = None
    outside = outdoor(traffic)
    try:
        walls, placement = room_walls(sid, traffic)
    except (OSError, KeyError, ValueError, ZeroDivisionError):
        walls, placement = None, {"status": "unknown", "reason": "The floor plan could not be used."}
    windows = rooms_with_window_detections(DATA / sid)
    results = {}
    for room_id, room in (rooms or {}).items():
        room_walls_ = walls.get(room_id) if walls is not None else None
        results[room_id] = {"type": room.get("type"), **indoor(room, outside, year, room_walls_,
                                                            window_detected=room_id in windows,
                                                            exterior=exterior)}
    return {"outdoor": outside, "rooms": results, "placement": placement, "year_built": year, "exterior": exterior,
            "indoor_limit_dnl": INDOOR_DNL_LIMIT, "assumptions": ASSUMPTIONS, "sources": traffic["sources"],
            "notes": traffic.get("notes", []), "fetched_at": traffic["fetched_at"]}

"""Which walls of each room face outside, and which way they face.

1. Outside walls come from the floor plan. Rooms are polygons in floor-plan pixels (100 px per metre). A room edge is
   on the outside if the space just beyond it, past the wall thickness, belongs to no other room. Unscanned spaces
   such as a garage also count as outside, so this leans towards more outside wall, never less.
2. Matterport floor plans are not aligned to north. We line the floor plan up with the building's footprint in
   OpenStreetMap: first the dominant wall angle (which fixes the rotation up to quarter turns), then the quarter turn
   whose outline best fits the footprint. A square or symmetric building can fit more than one way; every rotation
   that fits nearly as well is kept, and the noise estimate uses the loudest of them for each wall.
3. If the floor plan covers much less than the footprint (an office suite in a larger building), or no footprint is
   found, directions are unknown and each outside wall is assumed to face the traffic, as before.
"""
import json
import math

import requests

from app.sources.traffic import HEADERS, OVERPASS, metres

OFFSETS_M = (0.45, 1.1)          # look past the wall thickness, then a bit further for gaps between rooms
MIN_WALL_M = 0.4
FIT_TOLERANCE = 0.03             # placements within this overlap score of the best are kept as possible


def point_in_polygon(x, y, polygon):
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def polygon_area(polygon):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]))) / 2


def room_polygons(geometry):
    """Room outlines in metres, x east-ish and y up (floor-plan frame, not yet rotated to north)."""
    resolution = (geometry.get("floorplan") or {}).get("resolution") or 100.0
    return {room["id"]: [(x / resolution, -y / resolution) for x, y in room["polygon_px"]]
            for room in geometry["rooms"] if len(room.get("polygon_px") or []) >= 3}


def exterior_walls(geometry):
    """{room_id: [{"a", "b", "mid", "normal", "length_m"}]} for walls with no other room behind them."""
    polygons = room_polygons(geometry)
    walls = {}
    for room_id, polygon in polygons.items():
        others = [p for other, p in polygons.items() if other != room_id]
        found = []
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            length = math.hypot(x2 - x1, y2 - y1)
            if length < MIN_WALL_M:
                continue
            nx, ny = (y2 - y1) / length, -(x2 - x1) / length
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            if point_in_polygon(mx + nx * 0.05, my + ny * 0.05, polygon):
                nx, ny = -nx, -ny                       # make the normal point out of the room
            outside = 0
            for t in (0.2, 0.5, 0.8):
                px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
                if not any(point_in_polygon(px + nx * d, py + ny * d, other) for d in OFFSETS_M for other in others):
                    outside += 1
            if outside >= 2:
                found.append({"a": (x1, y1), "b": (x2, y2), "mid": (mx, my), "normal": (nx, ny),
                              "length_m": round(length, 2)})
        walls[room_id] = found
    return walls


# ---------------------------------------------------------------- orientation

def footprint_elements(directory, lat, lon):
    path = directory / "osm.json"
    if path.is_file():
        return json.loads(path.read_text())
    query = f'[out:json][timeout:60];way["building"](around:120,{lat},{lon});out tags geom;'
    for url in OVERPASS:
        try:
            response = requests.post(url, data={"data": query}, timeout=90, headers=HEADERS)
            response.raise_for_status()
            elements = response.json()["elements"]
            path.write_text(json.dumps(elements))
            return elements
        except (requests.RequestException, ValueError, KeyError):
            continue
    return []


def building_footprint(elements, lat, lon):
    """The OSM building outline containing the point, or the nearest one within 40 m, in local metres."""
    best = None
    for element in elements:
        points = [metres(lat, lon, p["lat"], p["lon"]) for p in element.get("geometry", [])]
        if len(points) < 4:
            continue
        polygon = points[:-1] if points[0] == points[-1] else points
        if point_in_polygon(0, 0, polygon):
            return polygon
        cx, cy = sum(x for x, _ in polygon) / len(polygon), sum(y for _, y in polygon) / len(polygon)
        distance = math.hypot(cx, cy)
        if distance < 40 and (best is None or distance < best[0]):
            best = (distance, polygon)
    return best[1] if best else None


def dominant_angle(polygons):
    """The wall direction modulo 90 degrees, weighted by wall length."""
    c = s = 0.0
    for polygon in polygons:
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            length = math.hypot(x2 - x1, y2 - y1)
            angle = math.atan2(y2 - y1, x2 - x1)
            c += length * math.cos(4 * angle)
            s += length * math.sin(4 * angle)
    return math.atan2(s, c) / 4


def rotate(points, angle, about=(0.0, 0.0)):
    ca, sa = math.cos(angle), math.sin(angle)
    ox, oy = about
    return [(ox + (x - ox) * ca - (y - oy) * sa, oy + (x - ox) * sa + (y - oy) * ca) for x, y in points]


def centroid(points):
    return sum(x for x, _ in points) / len(points), sum(y for _, y in points) / len(points)


def grid_inside(polygons, step=0.5):
    """Sample points on a grid inside any of the polygons."""
    xs = [x for p in polygons for x, _ in p]
    ys = [y for p in polygons for _, y in p]
    points = []
    y = min(ys) + step / 2
    while y < max(ys):
        x = min(xs) + step / 2
        while x < max(xs):
            if any(point_in_polygon(x, y, p) for p in polygons):
                points.append((x, y))
            x += step
        y += step
    return points


def fit_score(plan_samples, foot_samples, polygons, footprint, angle, plan_centre, shift):
    """Overlap of floor plan and footprint, both ways: F1 of the plan inside the footprint and the footprint
    inside the plan. Checking both ways is what tells a building from its mirror-turned copy."""
    px, py = plan_centre
    placed = [(x + shift[0], y + shift[1]) for x, y in rotate(plan_samples, angle, plan_centre)]
    precision = sum(point_in_polygon(x, y, footprint) for x, y in placed) / len(placed)
    back = rotate([(x - shift[0], y - shift[1]) for x, y in foot_samples], -angle, plan_centre)
    recall = sum(any(point_in_polygon(x, y, p) for p in polygons) for x, y in back) / len(back)
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def orientation(geometry, directory, lat, lon):
    """Possible placements of the floor plan in local east/north metres, or a reason directions are unknown."""
    polygons = list(room_polygons(geometry).values())
    if not polygons:
        return {"status": "unknown", "reason": "No room outlines in the floor plan."}
    footprint = building_footprint(footprint_elements(directory, lat, lon), lat, lon)
    if footprint is None:
        return {"status": "unknown", "reason": "No OpenStreetMap building outline found at this address."}
    plan_area = sum(polygon_area(p) for p in polygons)
    ratio = plan_area / max(polygon_area(footprint), 1.0)
    if ratio < 0.45:
        return {"status": "unknown", "reason": f"The scanned floor covers {ratio:.0%} of the building outline, "
                                               "likely one unit in a larger building."}
    plan_samples, foot_samples = grid_inside(polygons, 0.6), grid_inside([footprint], 0.6)
    plan_centre, foot_centre = centroid(plan_samples), centroid(foot_samples)
    base = dominant_angle([footprint]) - dominant_angle(polygons)
    fits = []
    for quarter in range(4):
        angle = base + quarter * math.pi / 2
        best = None
        for dx in (-2, -1, 0, 1, 2):            # centroids line up only roughly, so slide a little
            for dy in (-2, -1, 0, 1, 2):
                shift = (foot_centre[0] - plan_centre[0] + dx, foot_centre[1] - plan_centre[1] + dy)
                score = fit_score(plan_samples, foot_samples, polygons, footprint, angle, plan_centre, shift)
                if best is None or score > best[0]:
                    best = (score, shift)
        fits.append((best[0], angle, best[1]))
    fits.sort(key=lambda fit: -fit[0])
    top = fits[0][0]
    keep = [fit for fit in fits if fit[0] >= top - FIT_TOLERANCE]
    return {"status": "aligned" if len(keep) == 1 else "ambiguous", "fit": round(top, 2), "coverage": round(ratio, 2),
            "scores": [round(fit[0], 2) for fit in fits],
            "placements": [{"angle": angle, "shift": shift} for _, angle, shift in keep], "plan_centre": plan_centre,
            "footprint": footprint}


def edge_distance(x, y, polygon):
    from app.sources.traffic import segment_distance

    return min(segment_distance(x, y, *a, *b) for a, b in zip(polygon, polygon[1:] + polygon[:1]))


def place_walls(walls, plan_centre, placement, footprint=None):
    """Wall midpoints and outward normals in local east/north metres for one possible placement.

    With a footprint, a wall whose outside side lies well inside the building (an unscanned closet or cavity
    between rooms) is not an outside wall and is dropped."""
    angle, (sx, sy) = placement["angle"], placement["shift"]
    out = {}
    for room_id, items in walls.items():
        out[room_id] = []
        for wall in items:
            (mx, my), = rotate([wall["mid"]], angle, plan_centre)
            (nx, ny), = rotate([wall["normal"]], angle)
            mx, my = mx + sx, my + sy
            if footprint:
                probe = (mx + nx * 1.5, my + ny * 1.5)
                if point_in_polygon(*probe, footprint) and edge_distance(*probe, footprint) > 1.0:
                    continue
            out[room_id].append({**wall, "east_north": (mx, my), "facing": (nx, ny), "compass": compass(nx, ny)})
    return out


def compass(nx, ny):
    bearing = (math.degrees(math.atan2(nx, ny)) + 360) % 360
    return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][
        int((bearing + 22.5) // 45) % 8]

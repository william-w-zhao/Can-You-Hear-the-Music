"""Traffic near a building: roads from OpenStreetMap, with daily volumes from the best available public count.

Designed to work anywhere. For each nearby road, the daily volume (ADT) comes from, in order of preference:
1. FHWA HPMS, the federal Highway Performance Monitoring System: AADT that every US state reports for freeways,
   arterials and collectors, published per state by FHWA. Matched to OpenStreetMap roads by location, so it needs
   no street names. Also gives truck volumes and lane counts.
2. A local count provider where one exists. Los Angeles has LADOT counts (CC0), matched by street name, preferring
   a count at an intersection of two nearby roads. More cities can be added to LOCAL_PROVIDERS.
3. A typical volume for the road's OpenStreetMap class, scaled by its lane count. This works worldwide but is a
   stated assumption, not a measurement.

Every road records which of these it used, so the page and the agent can say how solid each number is.
"""
import json
import math
import re
import statistics
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests

from app.sources.config import DATA

OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
HPMS_URL = "https://geo.dot.gov/server/rest/services/Hosted/HPMS_FULL_{state}_{year}/FeatureServer/0"
HPMS_YEARS = (2024, 2023, 2022)
FCC_AREA_URL = "https://geo.fcc.gov/api/census/area"
LADOT_URL = "https://data.lacity.org/resource/94wu-3ps3.json?$limit=50000"
LADOT_DATASET = "https://data.lacity.org/Transportation/LADOT-Traffic-Counts-Summary/94wu-3ps3"
HPMS_DATASET = "https://www.fhwa.dot.gov/policyinformation/hpms.cfm"
LADOT_CACHE = DATA / "ladot_counts.json"
HEADERS = {"User-Agent": "can-you-hear-the-music (hackathon research)"}
RADIUS_M = 400
KEEP_GEOMETRY_M = 600
ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
                "living_street", "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link")
# Typical daily volumes per two-lane-equivalent and speeds by class, used only when no count exists.
TYPICAL_ADT = {"motorway": 150000, "trunk": 60000, "primary": 25000, "secondary": 15000, "tertiary": 6000,
               "unclassified": 1500, "residential": 800, "living_street": 300, "motorway_link": 12000,
               "trunk_link": 8000, "primary_link": 5000, "secondary_link": 3000, "tertiary_link": 2000}
TYPICAL_LANES = {"motorway": 8, "trunk": 4, "primary": 4, "secondary": 4, "tertiary": 2}
TYPICAL_KMH = {"motorway": 100, "trunk": 80, "primary": 56, "secondary": 56, "tertiary": 48,
               "unclassified": 40, "residential": 40, "living_street": 24, "motorway_link": 56,
               "trunk_link": 56, "primary_link": 40, "secondary_link": 40, "tertiary_link": 40}
TRUCK_SHARE = {"motorway": 0.08, "trunk": 0.06, "primary": 0.04, "secondary": 0.03, "tertiary": 0.02}
# A street-wide median is only trusted on through roads; long residential streets vary too much.
MEDIAN_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary"}
MATCH_M = 15            # an HPMS section matches an OSM road if it runs within this distance of it
# Street types are kept (Hill Drive is not Hill Street) but spelled one way.
SUFFIXES = {"STREET": "ST", "AVE": "AV", "AVENUE": "AV", "BOULEVARD": "BLVD", "BL": "BLVD", "DRIVE": "DR",
            "ROAD": "RD", "PLACE": "PL", "LANE": "LN", "COURT": "CT", "TERRACE": "TER", "PARKWAY": "PKWY",
            "HIGHWAY": "HWY", "CIRCLE": "CIR"}
DIRECTIONS = {"N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST"}


def street_key(name):
    """Normalise a street name so "N Figueroa Street" and "FIGUEROA ST" match."""
    words = re.sub(r"[^A-Z0-9 ]", " ", (name or "").upper()).split()
    words = [re.sub(r"^(\d+) ?(ST|ND|RD|TH)$", r"\1", word) for word in words]
    joined = " ".join(words)
    joined = re.sub(r"\b(\d+) (ST|ND|RD|TH)\b", r"\1", joined)        # "1 st ST" -> "1 ST"
    words = joined.split()
    while words and words[0] in DIRECTIONS:
        words = words[1:]
    while len(words) > 1 and words[-1] in DIRECTIONS:
        words = words[:-1]
    if len(words) > 1:
        words[-1] = SUFFIXES.get(words[-1], words[-1])
    return " ".join(words)


def metres(lat0, lon0, lat, lon):
    """Local flat-earth offset (east, north) in metres from (lat0, lon0); fine within a few kilometres."""
    return ((lon - lon0) * 111320 * math.cos(math.radians(lat0)), (lat - lat0) * 110540)


def segment_distance(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
    return math.hypot(px - x1 - t * dx, py - y1 - t * dy)


def distance_to_line(lat0, lon0, points):
    """Distance in metres from (lat0, lon0) to a polyline of (lat, lon) points."""
    xy = [metres(lat0, lon0, lat, lon) for lat, lon in points]
    return min((segment_distance(0, 0, *a, *b) for a, b in zip(xy, xy[1:])), default=math.inf)


def overpass_roads(lat, lon, radius=RADIUS_M):
    query = (f'[out:json][timeout:60];way["highway"~"^({"|".join(ROAD_CLASSES)})$"]'
             f"(around:{radius},{lat},{lon});out tags geom;")
    last = None
    for url in OVERPASS:
        for attempt in range(2):
            try:
                response = requests.post(url, data={"data": query}, timeout=90, headers=HEADERS)
                response.raise_for_status()
                return response.json()["elements"]
            except (requests.RequestException, ValueError, KeyError) as exc:
                last = exc
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"OpenStreetMap roads are unavailable right now ({type(last).__name__}). Try again.")


def parse_speed(text):
    match = re.match(r"(\d+)\s*(mph)?", text or "")
    if not match:
        return None
    return round(int(match.group(1)) * (1.609 if match.group(2) else 1))


def nearby_roads(lat, lon, elements):
    """One entry per named road (or per unnamed class), with its closest distance and its nearby geometry."""
    roads = {}
    for way in elements:
        tags, geometry = way.get("tags", {}), way.get("geometry", [])
        if len(geometry) < 2:
            continue
        points = [(p["lat"], p["lon"]) for p in geometry]
        name = tags.get("name") or tags.get("ref") or f"Unnamed {tags['highway']}"
        road_class = tags["highway"]
        key = (street_key(name), road_class if not tags.get("name") else "")
        road = roads.setdefault(key, {"name": name, "ref": tags.get("ref"), "class": road_class,
                                      "distance_m": math.inf, "lanes": None, "speed_kmh": None, "lines": []})
        distance = distance_to_line(lat, lon, points)
        if distance < road["distance_m"]:
            road.update(distance_m=round(distance, 1), class_=None)
            road["class"] = road_class
            road["osm_way_id"] = way.get("id")
        road.pop("class_", None)
        road["speed_kmh"] = road["speed_kmh"] or parse_speed(tags.get("maxspeed"))
        if tags.get("lanes", "").isdigit():
            road["lanes"] = max(road["lanes"] or 0, int(tags["lanes"]))
        kept = [[round(a, 6), round(b, 6)] for a, b in points
                if math.hypot(*metres(lat, lon, a, b)) < KEEP_GEOMETRY_M]
        if len(kept) >= 2:
            road["lines"].append(kept)
    return sorted((road for road in roads.values() if road["lines"]), key=lambda road: road["distance_m"])


# ---------------------------------------------------------------- FHWA HPMS (nationwide, US)

def us_state(lat, lon, hint=None):
    """Two-letter US state, from the listing when it has one, else the FCC census area API. None outside the US."""
    if hint and len(hint) == 2:
        return hint.upper()
    try:
        response = requests.get(FCC_AREA_URL, params={"lat": lat, "lon": lon, "format": "json"}, timeout=20,
                                headers=HEADERS)
        response.raise_for_status()
        results = response.json().get("results") or []
        return results[0].get("state_code") if results else None
    except (requests.RequestException, ValueError):
        return None


def hpms_sections(lat, lon, state, radius=RADIUS_M):
    """Road sections with AADT near the point, from the newest HPMS year published for the state."""
    fields = "objectid,aadt,f_system,through_lanes,aadt_single_unit,aadt_combination,speed_limit,routenumber,data_year"
    for year in HPMS_YEARS:
        layer = HPMS_URL.format(state=state, year=year)
        params = {"where": "aadt > 0", "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint",
                  "inSR": 4326, "distance": radius + 100, "units": "esriSRUnit_Meter", "outFields": fields,
                  "returnGeometry": "true", "outSR": 4326, "f": "json"}
        try:
            response = requests.get(layer + "/query", params=params, timeout=60,
                                    headers=HEADERS)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            continue
        if "error" in data:
            continue
        sections = []
        for feature in data.get("features", []):
            paths = (feature.get("geometry") or {}).get("paths") or []
            attributes = feature["attributes"]
            source_url = layer
            if attributes.get("objectid") is not None:
                query = urlencode({"objectIds": attributes["objectid"], "outFields": fields,
                                   "returnGeometry": "false", "f": "pjson"})
                source_url = f"{layer}/query?{query}"
            sections.append({**attributes, "source_url": source_url,
                             "paths": [[(y, x) for x, y in path] for path in paths]})
        return sections, year
    return [], None


def densify(points, lat0, lon0, step=10.0):
    xy = [metres(lat0, lon0, lat, lon) for lat, lon in points]
    out = []
    for (x1, y1), (x2, y2) in zip(xy, xy[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) // step))
        out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n)]
    return out + xy[-1:]


# HPMS functional classes an OpenStreetMap road class can plausibly be: 1 interstate, 2 freeway/expressway,
# 3 principal arterial, 4 minor arterial, 5 major collector, 6 minor collector, 7 local.
COMPATIBLE_SYSTEMS = {"motorway": {1, 2}, "motorway_link": {1, 2, 3}, "trunk": {1, 2, 3}, "trunk_link": {2, 3, 4},
                      "primary": {2, 3, 4}, "primary_link": {3, 4, 5}, "secondary": {3, 4, 5},
                      "secondary_link": {4, 5}, "tertiary": {4, 5, 6}, "tertiary_link": {5, 6},
                      "unclassified": {5, 6, 7}, "residential": {5, 6, 7}, "living_street": {6, 7}}
MIN_OVERLAP_M = 50      # the two must run alongside each other this far; a crossing street only overlaps ~2 x MATCH_M


def match_hpms(lat, lon, road, sections):
    """The HPMS section that runs along this road (not just across it), nearest the building, or None."""
    road_samples = [p for line in road["lines"] for p in densify(line, lat, lon) if math.hypot(*p) < RADIUS_M]
    road_xy = [[metres(lat, lon, a, b) for a, b in line] for line in road["lines"]]
    allowed = COMPATIBLE_SYSTEMS.get(road["class"], {5, 6, 7})
    # Freeway carriageways can sit 20-30 m from the HPMS centre line, and ramps share their class, so freeways
    # allow a wider gap and take the busiest matching section (the main line, not a ramp).
    freeway = road["class"] in ("motorway", "trunk")
    reach = 35.0 if freeway else MATCH_M

    def near(px, py, lines):
        return min(segment_distance(px, py, *a, *b) for line in lines for a, b in zip(line, line[1:])) <= reach

    best = None
    for section in sections:
        if section.get("f_system") not in allowed:
            continue
        section_xy = [[metres(lat, lon, a, b) for a, b in path] for path in section["paths"] if len(path) > 1]
        samples = [p for path in section["paths"] for p in densify(path, lat, lon) if math.hypot(*p) < RADIUS_M + 50]
        if not section_xy or not samples:
            continue
        along_road = sum(near(*p, section_xy) for p in road_samples) * 10.0
        along_section = sum(near(*p, road_xy) for p in samples) * 10.0
        if min(along_road, along_section) < MIN_OVERLAP_M:
            continue
        closeness = min(math.hypot(*p) for p in samples)
        score = (-section["aadt"], closeness) if freeway else (-min(along_road, along_section), closeness)
        if best is None or score < best[0]:
            best = (score, section)
    return best[1] if best else None


# ---------------------------------------------------------------- local providers

def ladot_counts():
    if LADOT_CACHE.is_file():
        return json.loads(LADOT_CACHE.read_text())
    response = requests.get(LADOT_URL, timeout=90, headers=HEADERS)
    response.raise_for_status()
    rows = [{"primary": row.get("primary_street", ""), "cross": row.get("cross_street", ""),
             "date": (row.get("count_date") or "")[:10], "type": row.get("type", ""),
             "total": int(float(row.get("total") or 0))} for row in response.json()]
    rows = [row for row in rows if row["total"] > 0]
    LADOT_CACHE.write_text(json.dumps(rows))
    return rows


# name, bounding box (south, west, north, east), loader, source label
LOCAL_PROVIDERS = [
    ("LADOT", (33.70, -118.67, 34.34, -118.15), ladot_counts, "City of Los Angeles, LADOT Traffic Counts Summary (CC0)"),
]


def local_counts(lat, lon):
    for name, (south, west, north, east), loader, label in LOCAL_PROVIDERS:
        if south <= lat <= north and west <= lon <= east:
            return name, loader(), label
    return None, [], None


def local_volume(road, counts, nearby_keys, provider):
    key = street_key(road["name"])
    rows = [row for row in counts if street_key(row["primary"]) == key]
    local = [row for row in rows if street_key(row["cross"]) in nearby_keys - {key}]
    if local:
        row = max(local, key=lambda row: row["date"])
        return row["total"], {"kind": "local_intersection",
                              "detail": f"{provider} count at {row['primary']} & {row['cross']}", "date": row["date"]}
    if rows and road["class"] in MEDIAN_CLASSES:
        return int(statistics.median(row["total"] for row in rows)), {
            "kind": "local_street", "detail": f"Median of {len(rows)} {provider} counts on {rows[0]['primary']}",
            "date": max(row["date"] for row in rows)}
    return None, None


# ---------------------------------------------------------------- combine

def typical_volume(road):
    base = TYPICAL_ADT.get(road["class"], 800)
    lanes, usual = road.get("lanes"), TYPICAL_LANES.get(road["class"])
    if lanes and usual:
        base = round(base * max(0.5, min(2.0, lanes / usual)))
    return base


def attach_volumes(lat, lon, roads, sections=(), counts=(), provider=None, hpms_year=None):
    nearby_keys = {street_key(road["name"]) for road in roads}
    for road in roads:
        road_class = road["class"]
        road["truck_share"] = TRUCK_SHARE.get(road_class, 0.01)
        speed_source = "OpenStreetMap speed limit" if road["speed_kmh"] else None
        section = match_hpms(lat, lon, road, sections) if sections else None
        if section:
            road["adt"] = int(section["aadt"])
            road["adt_source"] = {"kind": "hpms", "detail": f"FHWA HPMS {section.get('data_year') or hpms_year} AADT"
                                  + (f", route {section['routenumber']}" if section.get("routenumber") else ""),
                                  "date": str(section.get("data_year") or hpms_year), "url": section.get("source_url")}
            trucks = (section.get("aadt_single_unit") or 0) + (section.get("aadt_combination") or 0)
            if trucks:
                road["truck_share"] = round(min(0.4, trucks / section["aadt"]), 3)
            if section.get("through_lanes"):
                road["lanes"] = section["through_lanes"]
            if not road["speed_kmh"] and section.get("speed_limit"):
                road["speed_kmh"], speed_source = round(section["speed_limit"] * 1.609), "HPMS speed limit"
        else:
            volume, source = local_volume(road, counts, nearby_keys, provider) if counts else (None, None)
            if volume:
                road["adt"], road["adt_source"] = volume, source
            else:
                road["adt"] = typical_volume(road)
                road["adt_source"] = {"kind": "typical", "detail": f"Typical volume for a {road_class} road"
                                      + (f" with {road['lanes']} lanes" if road.get("lanes") else "")
                                      + " (no public count found)"}
        road["speed_kmh"] = road["speed_kmh"] or TYPICAL_KMH.get(road_class, 40)
        road["speed_source"] = speed_source or "typical for the road class"
    return roads


def building_location(sid):
    bundle = json.loads((DATA / sid / "bundle.json").read_text())
    box = bundle["vexcel"]["box"]
    return box["lat"], box["lon"]


def fetch_traffic(sid, *, refresh=False, state_hint=None):
    """Fetch and cache data/<sid>/traffic.json."""
    path = DATA / sid / "traffic.json"
    if path.is_file() and not refresh:
        cached = json.loads(path.read_text())
        if cached.get("version") == 2:
            return cached
    lat, lon = building_location(sid)
    roads = nearby_roads(lat, lon, overpass_roads(lat, lon))
    notes, sources = [], ["OpenStreetMap contributors (ODbL), road geometry, lanes and speed limits"]
    state = us_state(lat, lon, state_hint)
    sections, year = hpms_sections(lat, lon, state) if state else ([], None)
    if sections:
        sources.append(f"FHWA Highway Performance Monitoring System, {state} {year} (public domain)")
    elif state:
        notes.append(f"FHWA HPMS counts for {state} were unavailable; roads without local counts use typical volumes.")
    else:
        notes.append("Outside the US, roads use typical volumes for their class and lanes unless a local source exists.")
    provider, counts, label = None, [], None
    try:
        provider, counts, label = local_counts(lat, lon)
    except requests.RequestException:
        notes.append("Local city counts were unavailable.")
    if label:
        sources.append(label)
    result = {
        "version": 2,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "location": {"lat": lat, "lon": lon, "state": state,
                     "note": "Centre of the scan's aerial image, near the building."},
        "radius_m": RADIUS_M,
        "roads": attach_volumes(lat, lon, roads, sections, counts, provider, year),
        "notes": notes,
        "sources": sources,
    }
    path.write_text(json.dumps(result))
    return result


if __name__ == "__main__":
    import sys

    for sid in sys.argv[1:]:
        data = fetch_traffic(sid, refresh=True)
        print(sid, data["location"]["state"], data["sources"][1:])
        for road in data["roads"][:8]:
            print(f"  {road['name'][:28]:28} {road['class']:13} {road['distance_m']:6.0f} m  {road['adt']:>7} /day  "
                  f"{road['speed_kmh']} km/h  trucks {road['truck_share']:.0%}  {road['adt_source']['kind']}")

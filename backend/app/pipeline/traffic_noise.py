"""Street noise by hour: outdoors at the building, then inside each room through its walls and windows.

Outdoors, each road is a line of passing vehicles. A vehicle's level at 15 m comes from the FHWA reference energy
mean emission levels (FHWA-RD-77-108): autos 38.1·log10(S) − 2.4, medium trucks 33.9·log10(S) + 16.4, heavy trucks
24.6·log10(S) + 38.5 dB(A), S in km/h. A stream of N vehicles per hour at speed v (m/s) then gives, at distance D
from the road on hard ground,

    Leq(1 h) = L0 + 10·log10(π · D0 · N / (v · 3600)) + 10·log10(D0 / D),   D0 = 15 m.

Roads add on an energy basis. Daily volumes are spread over the day with a typical urban weekday profile.

Indoors, sound passes through the room's exterior wall and windows (EN 12354-3 style):

    L_in = L_out − R' + 10·log10(S / A),

with S the exterior facade area, A the room's absorption at 500 Hz, and R' the combined insulation of wall and glass.
Each outside wall comes from the floor plan (facades.py) with its own distance and direction to every road; wall and
window insulation come from photos of the outside (exterior.py). Without that geometry, a room with windows is
assumed to have one outside wall facing the traffic (the worst case). All results are estimates, and the page says so.
"""
import math
import re

D0 = 15.0
# Share of daily traffic in each hour, typical urban weekday (FHWA traffic monitoring guide shape), sums to 1.
HOURLY = [0.009, 0.006, 0.005, 0.005, 0.008, 0.018, 0.042, 0.064, 0.066, 0.056, 0.052, 0.054,
          0.056, 0.056, 0.060, 0.067, 0.074, 0.075, 0.062, 0.047, 0.037, 0.032, 0.026, 0.017]
HOURLY = [share / sum(HOURLY) for share in HOURLY]
INDOOR_FLOOR_DB = 18.0        # a quiet room never drops below fridge and ventilation hum
BACKGROUND_DB = 38.0          # distant city hum when no road is close (quiet LA residential night)
WALL_R = 42.0                 # stucco or brick exterior wall, traffic-weighted (Rw + Ctr)
GLASS_R = {"single": 24.0, "double": 30.0}
OPEN_WINDOW_R = 12.0          # a window open for air
INTERIOR_EXTRA = 10.0         # one more wall for a room with no windows
INDOOR_DNL_LIMIT = 45.0       # interior DNL goal for homes: HUD 24 CFR 51.104 (nationwide), California CBC 1206.4
SIDE_DB, REAR_DB = 4.0, 12.0  # a wall side-on to a road hears less; a wall facing away is shielded by the building


def energy(levels):
    return 10 * math.log10(sum(10 ** (level / 10) for level in levels)) if levels else -math.inf


def vehicle_levels(kmh):
    s = max(kmh, 20)
    return {"auto": 38.1 * math.log10(s) - 2.4, "medium": 33.9 * math.log10(s) + 16.4,
            "heavy": 24.6 * math.log10(s) + 38.5}


def road_leq(road, hour, distance=None):
    """One road's hourly Leq at the building (or at `distance` metres from it), in dB(A)."""
    per_hour = road["adt"] * HOURLY[hour]
    if per_hour <= 0:
        return -math.inf
    trucks = road.get("truck_share", 0.01)
    shares = {"auto": 1 - trucks, "medium": trucks * 0.6, "heavy": trucks * 0.4}
    speed = road["speed_kmh"] / 3.6
    distance = max(road["distance_m"] if distance is None else distance, 8.0)
    levels = vehicle_levels(road["speed_kmh"])
    return energy([
        levels[kind] + 10 * math.log10(math.pi * D0 * per_hour * share / (speed * 3600)) + 10 * math.log10(D0 / distance)
        for kind, share in shares.items() if share > 0
    ])


def dnl(hourly):
    """Day-night average level: night hours (22:00 to 07:00) count 10 dB louder."""
    return 10 * math.log10(sum(10 ** ((level + (10 if hour >= 22 or hour < 7 else 0)) / 10)
                               for hour, level in enumerate(hourly)) / 24)


def leq(hours, hourly):
    return 10 * math.log10(sum(10 ** (hourly[hour] / 10) for hour in hours) / len(hours))


NIGHT = [22, 23, 0, 1, 2, 3, 4, 5, 6]
DAY = list(range(7, 22))


def outdoor(traffic):
    """Hourly outdoor levels at the building and each road's share."""
    from app.sources.traffic import HPMS_DATASET, HPMS_URL, LADOT_DATASET

    hourly = [round(energy([road_leq(road, hour) for road in traffic["roads"]] + [BACKGROUND_DB]), 1)
              for hour in range(24)]
    roads = []
    hpms_layer = re.search(r"FHWA Highway Performance Monitoring System, ([A-Z]{2}) (\d{4})",
                           " ".join(traffic.get("sources", [])))
    for road in traffic["roads"]:
        day = leq(DAY, [road_leq(road, hour) for hour in range(24)])
        result = {**road, "day_leq": round(day, 1)}
        if "adt_source" in road:
            source = result["adt_source"] = dict(road["adt_source"])
            if source["kind"] == "hpms" and not source.get("url"):
                source["url"] = (HPMS_URL.format(state=hpms_layer[1], year=hpms_layer[2]) if hpms_layer else HPMS_DATASET)
            elif source["kind"].startswith("local_") and "LADOT" in source["detail"]:
                source["url"] = LADOT_DATASET
        roads.append(result)
    roads.sort(key=lambda road: -road["day_leq"])
    return {"hourly_db": hourly, "dnl": round(dnl(hourly), 1), "day_leq": round(leq(DAY, hourly), 1),
            "night_leq": round(leq(NIGHT, hourly), 1), "roads": roads}


def glazing(year):
    return "double" if year and year >= 1980 else "single"


def facade_r(wall_area, glass_area, glass_r, wall_r=WALL_R):
    glass_area = min(glass_area, wall_area * 0.8)
    tau = ((wall_area - glass_area) * 10 ** (-wall_r / 10) + glass_area * 10 ** (-glass_r / 10)) / wall_area
    return -10 * math.log10(tau)


def night_verdict(level):
    if level <= 30:
        return "Quiet at night"
    if level <= 35:
        return "Faint traffic at night"
    if level <= 45:
        return "Noticeable traffic at night"
    return "Loud traffic at night"


def facing_reduction(cosine):
    """dB less than a wall squarely facing the road: side-on walls see half the road, rear walls are shielded."""
    if cosine >= 0.25:
        return 0.0
    return SIDE_DB if cosine > -0.25 else REAR_DB


def wall_outdoor(wall, roads_xy, roads):
    """Hourly outdoor level at one outside wall, from each road's distance and direction."""
    mx, my = wall["east_north"]
    nx, ny = wall["facing"]
    per_road = []
    for road, lines in zip(roads, roads_xy):
        best = None
        for line in lines:
            for (x1, y1), (x2, y2) in zip(line, line[1:]):
                dx, dy = x2 - x1, y2 - y1
                t = max(0.0, min(1.0, ((mx - x1) * dx + (my - y1) * dy) / (dx * dx + dy * dy))) if dx or dy else 0
                qx, qy = x1 + t * dx, y1 + t * dy
                d = math.hypot(qx - mx, qy - my)
                if best is None or d < best[0]:
                    best = (d, qx, qy)
        if best is None:
            continue
        d, qx, qy = best
        cosine = ((qx - mx) * nx + (qy - my) * ny) / max(d, 0.1)
        per_road.append((road, d, facing_reduction(cosine)))
    return [round(energy([road_leq(road, hour, d) - cut for road, d, cut in per_road] + [BACKGROUND_DB]), 1)
            for hour in range(24)]


def indoor(room, outside, year=None, walls=None, *, window_detected=False, exterior=None):
    """Hourly indoor traffic noise, with an optional open-window scenario.

    `walls` lists the room's outside walls, each with its length and hourly outdoor level. None means the floor
    plan could not be used, so a positive glass estimate is used to model one exposed wall for the baseline.
    An open-window scenario needs both exterior-wall geometry and corroborating window evidence.
    `exterior` (exterior.py) gives wall and window insulation read from photos of the outside; without it the
    defaults (WALL_R, glazing by year) apply."""
    glass = room.get("glass_m2", 0) or 0
    window_scenario_available = bool(walls) and glass > 0 and window_detected
    opened = insulation_open = None
    absorption = max(room.get("absorption_500") or room["area_m2"] * 0.3, 1.0)
    pane = glazing(year)
    wall_r = (exterior or {}).get("wall_insulation_db", WALL_R)
    glass_r = (exterior or {}).get("window_insulation_db", GLASS_R[pane])
    if exterior and exterior.get("window_label"):
        pane = exterior["window_label"]
    height = room["height_m"]
    note = None
    if walls is None:
        if glass > 0:
            walls = [{"length_m": math.sqrt(room["area_m2"]), "hourly_db": outside["hourly_db"]}]
            exposure = "Floor-plan exposure unknown; estimated glass is modeled on one outside wall facing traffic"
        else:
            walls = []
            exposure = "Floor-plan exposure unknown and no glass estimated; modeled as an interior room"
    elif walls:
        directions = sorted({wall["compass"] for wall in walls if wall.get("compass")})
        length = sum(wall["length_m"] for wall in walls)
        exposure = (f"{length:.1f} m of outside wall from the floor plan"
                    + (f", facing {', '.join(directions)}" if directions else ", direction unknown"))
    else:
        exposure = "No outside wall in the floor plan, so treated as an interior room"
        if glass > 0:
            note = "The room has a glass estimate but the floor plan shows no outside wall; check this room."
    if walls:
        total = sum(wall["length_m"] for wall in walls)
        # Glass goes where windows were seen (glass_weight, from the panorama views); otherwise by wall length.
        weights = sum(wall.get("glass_weight", wall["length_m"]) for wall in walls)

        def through(window_r):
            levels = []
            for hour in range(24):
                parts = []
                for wall in walls:
                    area = wall["length_m"] * height
                    wall_glass = glass * wall.get("glass_weight", wall["length_m"]) / weights
                    parts.append(wall["hourly_db"][hour] - facade_r(area, wall_glass, window_r, wall_r)
                                 + 10 * math.log10(area / absorption))
                levels.append(round(energy(parts), 1))
            return levels

        closed = through(glass_r)
        main = max(walls, key=lambda wall: dnl(wall["hourly_db"]))
        main_area = main["length_m"] * height
        main_glass = glass * main.get("glass_weight", main["length_m"]) / weights
        insulation = facade_r(main_area, main_glass, glass_r, wall_r)
        if window_scenario_available:
            opened = through(OPEN_WINDOW_R)
            insulation_open = facade_r(main_area, main_glass, OPEN_WINDOW_R, wall_r)
    else:
        insulation = wall_r + INTERIOR_EXTRA
        area = math.sqrt(room["area_m2"]) * height
        closed = [round(level - insulation + 10 * math.log10(area / absorption), 1)
                  for level in outside["hourly_db"]]

    closed = [round(energy([level, INDOOR_FLOOR_DB]), 1) for level in closed]
    if opened is not None:
        opened = [round(energy([level, INDOOR_FLOOR_DB]), 1) for level in opened]
    night = leq(NIGHT, closed)
    return {
        "hourly_db": closed, "hourly_db_window_open": opened,
        "dnl": round(dnl(closed), 1), "dnl_window_open": round(dnl(opened), 1) if opened is not None else None,
        "night_leq": round(night, 1), "day_leq": round(leq(DAY, closed), 1),
        "quietest_hour": min(range(24), key=lambda hour: closed[hour]),
        "loudest_hour": max(range(24), key=lambda hour: closed[hour]),
        "verdict": night_verdict(night),
        "meets_indoor_limit": dnl(closed) <= INDOOR_DNL_LIMIT,
        "facade": {"exposure": exposure, "glazing": pane if walls and glass > 0 else None, "note": note,
                   "window_scenario_available": window_scenario_available,
                   "insulation_db": round(insulation, 1),
                   "insulation_open_db": round(insulation_open, 1) if insulation_open is not None else None},
    }


ASSUMPTIONS = [
    "Vehicle noise from the FHWA reference emission levels; roads add on an energy basis over hard ground.",
    "Daily volume spread over the day with a typical urban weekday profile; weekends are quieter.",
    "The outdoor chart uses the building's location; each outside wall uses its own distance to each road.",
    "Outside walls come from the floor plan; directions from lining it up with the OpenStreetMap building outline. "
    f"Walls side-on to a road get {SIDE_DB:.0f} dB less, walls facing away {REAR_DB:.0f} dB less (shielded by the "
    "building). Where the outline is missing or fits more than one way, the louder case is used.",
    "Wall and window insulation come from photos of the outside (or, failing that, the room photos), mapped to "
    f"typical Rw + Ctr values; with no photos, {WALL_R:.0f} dB walls and single glazing before 1980, double after. "
    "Where an open-window scenario is available, it assumes "
    f"the detected window can open and uses {OPEN_WINDOW_R:.0f} dB of insulation for the opening.",
    f"The comparison uses HUD's {INDOOR_DNL_LIMIT:.0f} dB DNL interior goal (24 CFR 51.101(a)(9)). "
    "The 30 dB nighttime bedroom reference comes from the WHO Guidelines for Community Noise.",
]

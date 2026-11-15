"""Traffic matching and the street-noise model. No network: sources are passed in."""
import math
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.pipeline import traffic_noise as noise
from app.pipeline import facades
from app.pipeline import street_noise
from app.pipeline.object_groups import detection_id
from app.sources import traffic


class StreetNameTests(TestCase):
    def test_names_match_across_sources_but_keep_street_type(self):
        self.assertEqual(traffic.street_key("N Figueroa Street"), traffic.street_key("FIGUEROA ST"))
        self.assertEqual(traffic.street_key("West Olympic Boulevard"), traffic.street_key("OLYMPIC BL"))
        self.assertEqual(traffic.street_key("1 st ST"), "1 ST")
        self.assertNotEqual(traffic.street_key("Hill Drive"), traffic.street_key("HILL ST"))

    def test_distance_to_a_road(self):
        lat, lon = 34.0, -118.0
        road = [(34.0 + 50 / 110540, -118.001), (34.0 + 50 / 110540, -117.999)]   # an east-west road 50 m north
        self.assertAlmostEqual(traffic.distance_to_line(lat, lon, road), 50, delta=0.5)


LAT, LON = 34.0, -118.0
EAST = 1 / (111320 * math.cos(math.radians(LAT)))      # degrees of longitude per metre here
NORTH = 1 / 110540


def line(x1, y1, x2, y2):
    """An east/north metre segment as (lat, lon) points."""
    return [[LAT + y1 * NORTH, LON + x1 * EAST], [LAT + y2 * NORTH, LON + x2 * EAST]]


def road(name, road_class, lines, distance=50, ref=None, speed=None, lanes=None):
    return {"name": name, "ref": ref, "class": road_class, "distance_m": distance, "speed_kmh": speed,
            "lanes": lanes, "lines": lines}


def section(aadt, f_system, x1, y1, x2, y2, **extra):
    points = line(x1, y1, x2, y2)
    return {"aadt": aadt, "f_system": f_system, "paths": [[tuple(p) for p in points]], "data_year": 2024, **extra}


class VolumeSourceTests(TestCase):
    counts = [{"primary": "FOUNTAIN AV", "cross": "BRONSON AV", "date": "2016-03-01", "total": 11000},
              {"primary": "FOUNTAIN AV", "cross": "VERMONT AV", "date": "2019-03-01", "total": 30000},
              {"primary": "MAPLE ST", "cross": "ELM ST", "date": "2018-01-01", "total": 5000}]

    def attach(self, roads, sections=(), counts=()):
        return {r["name"]: r for r in traffic.attach_volumes(LAT, LON, roads, list(sections), list(counts), "LADOT")}

    def test_federal_count_matches_a_road_running_alongside(self):
        main = road("Main Street", "secondary", [line(-200, 50, 200, 50)])
        roads = self.attach([main], [section(24000, 4, -200, 55, 200, 55, aadt_single_unit=600, aadt_combination=600)])
        self.assertEqual(roads["Main Street"]["adt"], 24000)
        self.assertEqual(roads["Main Street"]["adt_source"]["kind"], "hpms")
        self.assertAlmostEqual(roads["Main Street"]["truck_share"], 0.05)

    def test_crossing_street_does_not_take_the_main_road_count(self):
        side = road("Elm Street", "residential", [line(0, -150, 0, 150)])
        roads = self.attach([side], [section(30000, 5, -200, 50, 200, 50)])
        self.assertEqual(roads["Elm Street"]["adt_source"]["kind"], "typical")

    def test_residential_street_cannot_match_an_arterial(self):
        street = road("Oak Street", "residential", [line(-200, 20, 200, 20)])
        roads = self.attach([street], [section(30000, 3, -200, 22, 200, 22)])
        self.assertEqual(roads["Oak Street"]["adt_source"]["kind"], "typical")

    def test_freeway_takes_the_main_line_not_a_ramp(self):
        freeway = road("Ventura Freeway", "motorway", [line(-300, 130, 300, 130), line(-300, 150, 300, 150)])
        roads = self.attach([freeway], [section(20000, 2, -100, 120, 100, 125), section(186000, 1, -300, 140, 300, 140)])
        self.assertEqual(roads["Ventura Freeway"]["adt"], 186000)

    def test_local_count_at_a_nearby_intersection_when_no_federal_count(self):
        roads = self.attach([road("Fountain Avenue", "tertiary", [line(-200, 50, 200, 50)]),
                             road("North Bronson Avenue", "tertiary", [line(10, -200, 10, 200)])], counts=self.counts)
        self.assertEqual(roads["Fountain Avenue"]["adt"], 11000)
        self.assertEqual(roads["Fountain Avenue"]["adt_source"]["kind"], "local_intersection")

    def test_typical_volume_scales_with_lanes_and_ramps_are_not_freeways(self):
        roads = self.attach([road("Broad Avenue", "primary", [line(-200, 50, 200, 50)], lanes=8),
                             road("Unnamed motorway_link", "motorway_link", [line(-50, 80, 50, 90)])])
        self.assertEqual(roads["Broad Avenue"]["adt"], traffic.TYPICAL_ADT["primary"] * 2)
        self.assertLess(roads["Unnamed motorway_link"]["adt"], 20000)


class NoiseModelTests(TestCase):
    def stream(self, adt, distance=15, speed=50, trucks=0.0):
        return {"adt": adt, "distance_m": distance, "speed_kmh": speed, "truck_share": trucks}

    def test_reference_level_is_plausible(self):
        # About 1,000 cars an hour at 50 km/h, 15 m away, is roughly 62 dB(A).
        hour = 8
        level = noise.road_leq(self.stream(1000 / noise.HOURLY[hour]), hour)
        self.assertAlmostEqual(level, 62, delta=1.5)

    def test_doubling_distance_from_a_road_lowers_it_3_db(self):
        near, far = (noise.road_leq(self.stream(20000, distance), 12) for distance in (20, 40))
        self.assertAlmostEqual(near - far, 3.0, places=1)

    def test_hourly_profile_sums_to_one(self):
        self.assertAlmostEqual(sum(noise.HOURLY), 1.0, places=2)

    def test_dnl_penalises_night(self):
        self.assertAlmostEqual(noise.dnl([50.0] * 24), 50 + 10 * math.log10((15 + 9 * 10) / 24), places=3)

    def test_indoor_is_quieter_and_open_window_is_louder(self):
        outside = noise.outdoor({"roads": [{**self.stream(150000, 130, 105, 0.08), "name": "Freeway"}]})
        room = {"area_m2": 20, "height_m": 2.6, "glass_m2": 4, "absorption_500": 8}
        walls = [{"length_m": math.sqrt(room["area_m2"]), "hourly_db": outside["hourly_db"]}]
        result = noise.indoor(room, outside, year=1937, walls=walls, window_detected=True)
        self.assertLess(result["dnl"], outside["dnl"] - 20)
        self.assertGreater(result["dnl_window_open"], result["dnl"])
        self.assertTrue(result["facade"]["window_scenario_available"])
        self.assertEqual(result["facade"]["glazing"], "single")
        interior = noise.indoor({**room, "glass_m2": 0}, outside, year=1937)
        self.assertLess(interior["dnl"], result["dnl"])

        for candidate, exterior, seen in ((room, walls, False), (room, [], True), (room, None, True),
                                          ({**room, "glass_m2": 0}, walls, True)):
            with self.subTest(exterior=exterior, seen=seen, glass=candidate["glass_m2"]):
                baseline = noise.indoor(candidate, outside, walls=exterior, window_detected=seen)
                self.assertFalse(baseline["facade"]["window_scenario_available"])
                self.assertIsNone(baseline["dnl_window_open"])
                self.assertIsNone(baseline["hourly_db_window_open"])
                self.assertEqual(len(baseline["hourly_db"]), 24)

    def test_window_evidence_honors_saved_reviews(self):
        window = {"label": "window", "face_index": 1, "box_px": [1, 2, 3, 4], "needs_review": False}
        low_score = {**window, "needs_review": True}
        key = detection_id(window)
        hits = {"visible": window, "uncertain": low_score, "kept": low_score, "dismissed": window,
                "relabeled": {**low_score, "label": "mirror"}}
        with TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "vision.json").write_text(json.dumps({"indoor": {"rooms": {
                room_id: {"detections": [hit]} for room_id, hit in hits.items()
            }}}))
            (directory / "room_reviews.json").write_text(json.dumps({
                "kept": {"kept": [key]}, "dismissed": {"labels": {key: "dismiss"}},
                "relabeled": {"labels": {detection_id(hits["relabeled"]): "window"}},
            }))
            self.assertEqual(street_noise.rooms_with_window_detections(directory), {"visible", "kept", "relabeled"})


def rooms_geometry(rooms):
    """Floor-plan geometry from {room_id: [(x, y) metres]}, at 100 px per metre (pixel y points down)."""
    return {"floorplan": {"resolution": 100.0},
            "rooms": [{"id": rid, "polygon_px": [(x * 100, -y * 100) for x, y in poly]} for rid, poly in rooms.items()]}


class FacadeTests(TestCase):
    # Two rooms side by side with a 0.15 m wall between them: 8 m x 5 m overall.
    geometry = rooms_geometry({"west": [(0, 0), (4, 0), (4, 5), (0, 5)],
                               "east": [(4.15, 0), (8, 0), (8, 5), (4.15, 5)]})

    def test_shared_wall_is_not_outside(self):
        walls = facades.exterior_walls(self.geometry)
        self.assertEqual(len(walls["west"]), 3)
        self.assertAlmostEqual(sum(w["length_m"] for w in walls["west"]), 4 + 5 + 4)
        self.assertFalse(any(abs(w["mid"][0] - 4) < 0.1 for w in walls["west"]))

    def test_floor_plan_turned_onto_an_l_shaped_footprint(self):
        plan = {"a": [(0, 0), (10, 0), (10, 4), (0, 4)], "b": [(0, 4.15), (4, 4.15), (4, 10), (0, 10)]}
        geometry = rooms_geometry(plan)
        turn = math.radians(30)
        outline = [(0, 0), (10, 0), (10, 4), (4, 4), (4, 10), (0, 10)]
        footprint = facades.rotate(outline, turn)
        with patch.object(facades, "footprint_elements", return_value=[]), \
                patch.object(facades, "building_footprint", return_value=footprint):
            placed = facades.orientation(geometry, None, LAT, LON)
        self.assertEqual(placed["status"], "aligned")
        angle = math.degrees(placed["placements"][0]["angle"]) % 360
        self.assertAlmostEqual(angle, 30, delta=3)

    def test_suite_in_a_large_building_has_unknown_directions(self):
        big = [(0, 0), (60, 0), (60, 40), (0, 40)]
        with patch.object(facades, "footprint_elements", return_value=[]), \
                patch.object(facades, "building_footprint", return_value=big):
            self.assertEqual(facades.orientation(self.geometry, None, LAT, LON)["status"], "unknown")

    def test_wall_facing_away_from_the_road_is_quieter(self):
        roads = [{"adt": 100000, "speed_kmh": 100, "truck_share": 0.05, "distance_m": 50}]
        roads_xy = [[[(-300, 50), (300, 50)]]]                     # road 50 m north
        facing = {"east_north": (0, 0), "facing": (0, 1)}
        away = {"east_north": (0, 0), "facing": (0, -1)}
        near = noise.wall_outdoor(facing, roads_xy, roads)
        far = noise.wall_outdoor(away, roads_xy, roads)
        self.assertAlmostEqual(near[12] - far[12], noise.REAR_DB, delta=0.5)


class OpenWindowTests(TestCase):
    def test_bigger_opening_lets_in_more(self):
        closed = noise.facade_r(10, 2, 30, 42)
        small = noise.facade_r(10, 2, 30, 42, open_area=0.1)
        large = noise.facade_r(10, 2, 30, 42, open_area=0.5)
        self.assertGreater(closed, small)
        self.assertGreater(small, large)
        self.assertAlmostEqual(large, -10 * math.log10((8 * 10 ** -4.2 + 1.5 * 10 ** -3 + 0.5) / 10), places=6)

    def test_opening_cannot_exceed_the_glass(self):
        self.assertEqual(noise.facade_r(10, 0.2, 30, 42, open_area=5), noise.facade_r(10, 0.2, 30, 42, open_area=0.2))

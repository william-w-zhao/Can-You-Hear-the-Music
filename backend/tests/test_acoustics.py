import json
from unittest import TestCase

from app.pipeline.acoustics import room_acoustics, rt60
from app.sources.config import DATA


class SurfaceAcousticsTests(TestCase):
    room = {"area_m2": 20, "height_m": 2.5, "perimeter_m": 18, "volume_m3": 50}
    materials = {"floor": "concrete", "ceiling": "drywall_ceiling", "walls": "drywall", "glass_m2": 10}

    def test_panels_replace_opaque_wall_absorption(self):
        baseline, absorption = rt60(self.room, self.materials)
        treated = {**self.materials, "wall_panel_m2": 4}
        times, treated_absorption = rt60(self.room, treated)
        self.assertAlmostEqual(treated_absorption[1] - absorption[1], 4 * (0.90 - 0.05))
        self.assertLess(times[1], baseline[1])
        self.assertEqual(room_acoustics(self.room, treated)["surface_m2"], 85)
        with self.assertRaisesRegex(ValueError, "opaque wall area"):
            rt60(self.room, {**treated, "wall_panel_m2": 36})

    def test_surface_override_changes_only_its_band_and_area(self):
        baseline, absorption = rt60(self.room, self.materials)
        override = {"walls": {"500": 0.4}}
        times, updated = rt60(self.room, self.materials, absorption=override)
        self.assertEqual((times[0], times[2]), (baseline[0], baseline[2]))
        self.assertAlmostEqual(updated[1] - absorption[1], 35 * (0.4 - 0.05))
        with self.assertRaises(ValueError):
            rt60(self.room, self.materials, absorption={"walls": {"500": 1.1}})


class CoverageTests(TestCase):
    room = {"area_m2": 12, "height_m": 2.5, "perimeter_m": 14, "volume_m3": 30}
    kitchen = {"floor": "ceramic_tile", "ceiling": "drywall_ceiling", "walls": "plaster", "glass_m2": 2}

    def test_cabinetry_replaces_its_share_of_bare_wall(self):
        _, bare = rt60(self.room, self.kitchen)
        _, covered = rt60(self.room, {**self.kitchen, "wall_coverage": {"cabinetry": 0.25}})
        wall = 14 * 2.5 - 2
        self.assertAlmostEqual(covered[1] - bare[1], wall * 0.25 * (0.10 - 0.06), places=6)

    def test_rug_softens_a_hard_floor_but_not_a_carpet(self):
        _, bare = rt60(self.room, self.kitchen)
        _, rug = rt60(self.room, {**self.kitchen, "floor_coverage": {"rug": 0.3, "rug_seen": True}})
        self.assertAlmostEqual(rug[1] - bare[1], 12 * 0.3 * (0.25 - 0.01), places=6)
        carpet = {**self.kitchen, "floor": "carpet_on_pad"}
        self.assertEqual(rt60(self.room, carpet)[1], rt60(self.room, {**carpet, "floor_coverage": {"rug": 0.3}})[1])
        _, mat = rt60(self.room, {**self.kitchen, "type": "Bathroom", "floor_coverage": {"rug": 0, "rug_seen": True}})
        self.assertAlmostEqual(mat[1] - bare[1], 12 * 0.10 * (0.25 - 0.01), places=6)

    def test_coverage_is_capped(self):
        surfaces_area = room_acoustics(self.room, {**self.kitchen, "wall_coverage": {"cabinetry": 0.9, "shelving": 0.9}})
        self.assertEqual(surfaces_area["surface_m2"], room_acoustics(self.room, self.kitchen)["surface_m2"])


class CachedAcousticsTests(TestCase):
    def test_saved_room_metrics(self):
        for sid, count in {"hLR2zAFV1tK": 11, "zvKHR9DHNjJ": 13}.items():
            with self.subTest(scan=sid):
                directory = DATA / sid
                required = [directory / name for name in ("rooms.json", "materials.json", "acoustics.json")]
                if not all(path.is_file() for path in required):
                    self.skipTest(f"Demo cache unavailable for {sid}")
                geometry, materials, cached = [json.loads(path.read_text()) for path in required]
                expected = {room["id"]: room for room in cached["rooms"]}
                self.assertEqual(len(expected), count)
                self.assertEqual({room["id"] for room in geometry["rooms"]}, expected.keys())
                for room in geometry["rooms"]:
                    with self.subTest(room=room["id"]):
                        saved = expected[room["id"]]
                        labels = {**materials["rooms"][room["id"]],
                                  **({"wall_coverage": saved["wall_coverage"]} if "wall_coverage" in saved else {}),
                                  **({"floor_coverage": saved["floor_coverage"]} if "floor_coverage" in saved else {})}
                        metrics = room_acoustics(room, labels)
                        self.assertEqual(metrics, {key: expected[room["id"]][key] for key in metrics})

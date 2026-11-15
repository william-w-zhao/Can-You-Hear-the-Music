"""Cabinet runs and wall coverage from YOLO boxes, glass placed on walls with seen windows, wall insulation mixes."""
import math
from unittest import TestCase

from app.pipeline import exterior, street_noise, vision


def hit(label, box, view="Wall 1", confidence=0.6, review=False):
    return {"label": label, "box_px": box, "sheet_box_px": box, "view": view, "confidence": confidence,
            "needs_review": review}


class CabinetRunTests(TestCase):
    def test_side_by_side_cabinet_doors_become_one_run(self):
        hits = [hit("cabinet", [10, 100, 60, 180]), hit("cabinet", [62, 102, 110, 182]), hit("cabinet", [113, 98, 160, 179]),
                hit("cabinet", [10, 100, 60, 180], view="Wall 2"), hit("door", [170, 40, 199, 199])]
        merged = vision.merge_runs(hits, 200)
        runs = [h for h in merged if h["label"] == "cabinet"]
        self.assertEqual(sorted(h["parts"] for h in runs), [1, 3])
        self.assertEqual(next(h for h in runs if h["parts"] == 3)["box_px"], [10, 98, 160, 182])
        self.assertEqual(sum(h["label"] == "door" for h in merged), 1)

    def test_upper_and_lower_cabinets_stay_separate(self):
        merged = vision.merge_runs([hit("cabinet", [10, 10, 100, 60]), hit("cabinet", [10, 120, 100, 190])], 200)
        self.assertEqual(len(merged), 2)

    def test_coverage_counts_overlaps_once(self):
        hits = [hit("cabinet", [0, 0, 100, 200]), hit("cabinet", [50, 0, 100, 200]), hit("cabinet", [0, 0, 200, 200], review=True)]
        coverage = vision.wall_coverage(hits, 200)
        self.assertAlmostEqual(coverage["cabinet"], 0.5 / 4, places=2)      # half of one of four wall views


class GlassPlacementTests(TestCase):
    def test_wall_facing_a_seen_window_takes_more_glass(self):
        walls = {"r1": [{"normal": (1, 0), "length_m": 4.0}, {"normal": (0, 1), "length_m": 4.0}]}
        street_noise.weight_glass(walls, {"r1": [(0.98, 0.1)]})
        east, north = walls["r1"]
        self.assertEqual((east["window_seen"], north["window_seen"]), (True, False))
        self.assertEqual(east["glass_weight"], 4 * street_noise.WINDOW_WEIGHT)

    def test_no_seen_windows_leaves_walls_unweighted(self):
        walls = {"r1": [{"normal": (1, 0), "length_m": 4.0}]}
        street_noise.weight_glass(walls, {})
        self.assertNotIn("glass_weight", walls["r1"][0])


class ExteriorTests(TestCase):
    def test_default_depends_on_type_and_year(self):
        house = exterior.default_assessment("residential", 1937)
        office = exterior.default_assessment("commercial", None)
        self.assertEqual((house["walls"][0]["material"], house["windows"]), ("stucco_wood_frame", "single_pane"))
        self.assertEqual((office["walls"][0]["material"], office["windows"]), ("concrete", "double_pane"))

    def test_mixed_wall_insulation_is_dominated_by_the_weaker_part(self):
        brick, stucco = exterior.WALLS["brick_veneer"][1], exterior.WALLS["stucco_wood_frame"][1]
        mixed = -10 * math.log10(0.5 * 10 ** (-brick / 10) + 0.5 * 10 ** (-stucco / 10))
        self.assertLess(mixed, (brick + stucco) / 2)
        self.assertGreater(mixed, stucco)


class SoftObjectRuleTests(TestCase):
    def test_rug_far_away_through_a_doorway_is_dropped(self):
        near = hit("rug", [40, 150, 160, 195])
        far = hit("rug", [95, 120, 105, 128])          # tiny: seen in the next room
        high = hit("rug", [40, 20, 160, 80])           # a rug cannot float in the upper part of a wall view
        self.assertEqual([vision.plausible(h, "Wall 1", 200) for h in (near, far, high)], [True, False, False])
        self.assertTrue(vision.plausible(far, "Floor", 200))

    def test_no_window_or_furniture_on_the_ceiling(self):
        self.assertFalse(vision.plausible(hit("window", [10, 10, 50, 50]), "Ceiling", 200))
        self.assertTrue(vision.plausible(hit("window", [10, 10, 50, 50]), "Wall 2", 200))

    def test_floor_rug_share_is_measured_in_the_floor_view(self):
        self.assertEqual(vision.floor_coverage([hit("rug", [0, 0, 100, 200], view="Floor")], 200),
                         {"rug": 0.5, "rug_seen": True})
        self.assertEqual(vision.floor_coverage([hit("rug", [0, 150, 100, 200])], 200), {"rug": 0.0, "rug_seen": True})
        self.assertEqual(vision.floor_coverage([hit("rug", [0, 0, 100, 200], view="Floor", review=True)], 200), {})

    def test_soft_items_have_a_lower_bar_than_other_objects(self):
        self.assertLess(vision.LABEL_REVIEW_BELOW["rug"], vision.REVIEW_BELOW)

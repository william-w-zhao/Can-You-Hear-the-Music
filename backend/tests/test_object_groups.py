import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import acoustics
from app.main import app
from app.pipeline.object_groups import detection_id, group_detections, merge_decisions, split_decisions

SIZE = 200
WALL_2, WALL_3 = 2, 3          # adjacent faces: Wall 2's right edge meets Wall 3's left edge


def hit(label, face, box, confidence=0.9):
    view = {0: "Ceiling", 1: "Wall 1", 2: "Wall 2", 3: "Wall 3", 4: "Wall 4", 5: "Floor"}[face]
    return {"label": label, "face_index": face, "view": view, "box_px": box, "confidence": confidence,
            "needs_review": confidence < 0.3, "panorama_id": "p1"}


def group_of(inventory, item):
    return next(group for group in inventory["groups"] if detection_id(item) in group["detection_ids"])


class GroupingTests(TestCase):
    def test_object_split_across_a_seam_is_one_object(self):
        left = hit("sofa", WALL_2, [170, 120, 200, 200])
        right = hit("sofa", WALL_3, [0, 125, 120, 200])
        inventory = group_detections([left, right], SIZE, {})
        self.assertEqual(len(inventory["groups"]), 1)
        self.assertEqual(inventory["groups"][0]["views"], ["Wall 2", "Wall 3"])
        self.assertEqual(inventory["reviews"], [])

    def test_nested_duplicate_does_not_block_the_seam_match(self):
        # The living-room sofa: a second, smaller low-score sofa box inside the big one on Wall 3.
        left = hit("sofa", WALL_2, [170.7, 123.6, 200, 200], 0.91)
        big = hit("sofa", WALL_3, [0, 129.5, 128.6, 200], 0.86)
        small = hit("sofa", WALL_3, [0, 131.3, 50.1, 200], 0.19)
        inventory = group_detections([left, big, small], SIZE, {})
        self.assertEqual(len(inventory["groups"]), 1)

    def test_same_box_with_two_labels_is_one_object(self):
        table = hit("table", WALL_3, [33.3, 129, 74.9, 152.1], 0.12)
        desk = hit("desk", WALL_3, [33.4, 128.8, 74.8, 152.2], 0.16)
        inventory = group_detections([table, desk], SIZE, {})
        self.assertEqual(len(inventory["groups"]), 1)
        self.assertEqual(inventory["groups"][0]["label"], "desk")      # named after the higher score

    def test_related_labels_across_a_seam_need_review_when_uncertain(self):
        sofa = hit("sofa", WALL_2, [150, 120, 200, 200], 0.9)
        chair = hit("chair", WALL_3, [0, 160, 30, 200], 0.9)        # meets the seam but overlaps weakly
        inventory = group_detections([sofa, chair], SIZE, {})
        self.assertEqual(len(inventory["groups"]), 2)
        self.assertEqual(len(inventory["reviews"]), 1)

    def test_unrelated_labels_at_a_seam_are_not_candidates(self):
        sofa = hit("sofa", WALL_2, [170, 120, 200, 200])
        window = hit("window", WALL_3, [0, 125, 120, 200])
        inventory = group_detections([sofa, window], SIZE, {})
        self.assertEqual(len(inventory["groups"]), 2)
        self.assertEqual(inventory["reviews"], [])

    def test_two_candidates_on_the_other_side_go_to_review(self):
        left = hit("chair", WALL_2, [170, 100, 200, 200])
        upper = hit("chair", WALL_3, [0, 100, 40, 150])
        lower = hit("chair", WALL_3, [0, 150, 40, 200])
        inventory = group_detections([left, upper, lower], SIZE, {})
        self.assertEqual(len(inventory["groups"]), 3)
        self.assertTrue(inventory["reviews"])

    def test_separate_decision_blocks_automatic_merge(self):
        left = hit("sofa", WALL_2, [170, 120, 200, 200])
        right = hit("sofa", WALL_3, [0, 125, 120, 200])
        pair = ":".join(sorted((detection_id(left), detection_id(right))))
        inventory = group_detections([left, right], SIZE, {pair: "separate"})
        self.assertEqual(len(inventory["groups"]), 2)

    def test_manual_merge_and_split_any_detections(self):
        hits = [hit("chair", 1, [10, 10, 50, 50]), hit("table", 4, [80, 80, 150, 150]), hit("rug", 5, [0, 0, 90, 90])]
        ids = [detection_id(item) for item in hits]
        merged = merge_decisions(hits, SIZE, {}, ids)
        self.assertEqual(len(group_detections(hits, SIZE, merged)["groups"]), 1)
        split = split_decisions(hits, SIZE, merged, ids)
        self.assertEqual(len(group_detections(hits, SIZE, split)["groups"]), 3)
        # Merging again overrides the earlier "separate" decisions among the chosen boxes.
        again = merge_decisions(hits, SIZE, split, ids[:2])
        self.assertEqual(len(group_detections(hits, SIZE, again)["groups"]), 2)

    def test_saved_low_score_merge_is_counted_without_rerunning_review(self):
        hits = [hit("sofa", WALL_2, [170, 120, 200, 200], 0.21), hit("sofa", WALL_3, [0, 125, 120, 200], 0.22)]
        ids = [detection_id(item) for item in hits]
        before = group_detections(hits, SIZE, {})["groups"]
        self.assertEqual([item["status"] for item in before], ["low_score", "low_score"])
        after = group_detections(hits, SIZE, merge_decisions(hits, SIZE, {}, ids))["groups"]
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0]["status"], "estimated")
        self.assertTrue(after[0]["confirmed"])
        self.assertEqual(after[0]["confidence"], 0.22)


class InventoryApiTests(TestCase):
    def test_keep_merge_and_split_low_score_objects_persist(self):
        hits = [hit("chair", WALL_2, [170, 120, 200, 200], 0.21), hit("chair", WALL_3, [0, 125, 120, 200], 0.22)]
        ids = [detection_id(item) for item in hits]
        base = "/api/buildings/testscan/rooms/r1/acoustics/object-review"
        with TemporaryDirectory() as data, patch("app.api.cache.DATA", Path(data)), TestClient(app) as client:
            scan = Path(data) / "testscan"
            scan.mkdir()
            evidence = {"status": "complete", "width": acoustics.SHEET_MARGIN + len(acoustics.VIEWS) * SIZE,
                        "rooms": {"r1": {"detections": hits}}}
            (scan / "vision.json").write_text(json.dumps({"indoor": evidence}))

            kept = client.post(f"{base}/keep", json={"detection_ids": ids}).raise_for_status().json()["groups"]
            self.assertEqual(len(kept), 2)
            self.assertTrue(all(g["confirmed"] and g["status"] != "low_score" for g in kept))
            merged = client.post(f"{base}/merge", json={"detection_ids": ids}).raise_for_status().json()["groups"]
            self.assertEqual(len(merged), 1)
            self.assertEqual(set(merged[0]["detection_ids"]), set(ids))
            reloaded, size = acoustics.indoor_evidence("testscan", "r1", scan)
            self.assertEqual(group_detections(reloaded["detections"], size, acoustics.object_decisions("testscan", "r1"))["groups"], merged)
            split = client.post(f"{base}/split", json={"detection_ids": ids}).raise_for_status().json()["groups"]
            self.assertEqual(len(split), 2)
            self.assertTrue(all(g["confirmed"] and g["status"] != "low_score" for g in split))
            self.assertEqual(json.loads((scan / "vision.json").read_text())["indoor"]["rooms"]["r1"]["detections"], hits)

from unittest import TestCase

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

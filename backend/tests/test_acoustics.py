import json
from unittest import TestCase

from app.pipeline.acoustics import room_acoustics
from app.sources.config import DATA


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
                        metrics = room_acoustics(room, materials["rooms"][room["id"]])
                        self.assertEqual(metrics, {key: expected[room["id"]][key] for key in metrics})

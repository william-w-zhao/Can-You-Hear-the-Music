"""Saving reviewed materials must not depend on the in-memory analysis job, which a restart forgets."""
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.api import jobs
from app.pipeline.materials import RoomMaterials

LABELS = RoomMaterials(type="Kitchen", floor="ceramic_tile", ceiling="drywall_ceiling", walls="plaster",
                       furnishing="cabinets", glass_m2=1.5)


class SaveMaterialsTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        (self.data / "scan1").mkdir()
        for target, value in (("DATA", self.data), ("jobs", {}), ("latest", {})):
            patcher = patch.object(jobs, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        submit = patch.object(jobs.worker, "submit")
        self.submit = submit.start()
        self.addCleanup(submit.stop)

    def test_saves_and_calculates_without_a_job(self):
        result = jobs.save_materials("scan1", {"r1": LABELS}, ["r1"])
        saved = json.loads((self.data / "scan1" / "materials.json").read_text())
        self.assertEqual(saved["rooms"]["r1"]["floor"], "ceramic_tile")
        self.assertEqual(jobs.jobs[result["job_id"]]["status"], "running")
        self.submit.assert_called_once_with(jobs.run_job, result["job_id"], "scan1")

    def test_reuses_the_waiting_job(self):
        jobs.jobs["j1"] = {"sid": "scan1", "status": "needs_materials", "review": {"rooms": [{"id": "r1"}]}}
        jobs.latest["scan1"] = "j1"
        self.assertEqual(jobs.save_materials("scan1", {"r1": LABELS}, ["r1"]), {"job_id": "j1"})

    def test_requires_every_room(self):
        with self.assertRaises(HTTPException) as caught:
            jobs.save_materials("scan1", {"r1": LABELS}, ["r1", "r2"])
        self.assertEqual(caught.exception.status_code, 422)
        self.assertFalse((self.data / "scan1" / "materials.json").exists())

    def test_refuses_while_analysis_is_running(self):
        jobs.jobs["j1"] = {"sid": "scan1", "status": "running"}
        jobs.latest["scan1"] = "j1"
        with self.assertRaises(HTTPException) as caught:
            jobs.save_materials("scan1", {"r1": LABELS}, ["r1"])
        self.assertEqual(caught.exception.status_code, 409)

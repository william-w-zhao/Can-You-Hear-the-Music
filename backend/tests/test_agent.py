"""The investigator's tools and the thread that turns agent updates into page events.

The model itself is not called here; a live run is a manual check (see README)."""
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

from app.agent.tools import APPROVAL_TOOL, building_tools
from app.api.agent import Thread
from app.pipeline.acoustics import room_acoustics

ROOM = {"id": "r1", "type": "Kitchen", "area_m2": 12.0, "perimeter_m": 14.0, "height_m": 2.5, "volume_m3": 30.0,
        "floor": "vinyl_tile", "ceiling": "drywall_ceiling", "walls": "drywall", "glass_m2": 2.0,
        "furnishing": "cabinets"}


class ScanTestCase(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data = Path(folder.name)
        (self.data / "scan1").mkdir()
        room = {**ROOM, **room_acoustics(ROOM, ROOM)}
        (self.data / "scan1" / "acoustics.json").write_text(json.dumps({"rooms": [room]}))
        (self.data / "scan1" / "rooms.json").write_text(json.dumps({"rooms": [ROOM]}))
        patcher = patch("app.api.cache.DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tools = building_tools("scan1")


class ToolTests(ScanTestCase):
    def test_list_rooms_reports_engine_numbers(self):
        rooms = self.tools["list_rooms"].invoke({})
        self.assertEqual([room["id"] for room in rooms], ["r1"])
        self.assertEqual(rooms[0]["rt60"], room_acoustics(ROOM, ROOM)["rt60"])

    def test_what_if_compares_without_saving(self):
        result = self.tools["what_if"].invoke({"room_id": "r1", "ceiling": "acoustic_tile"})
        self.assertLess(result["after"]["rt60"][1], result["before"]["rt60"][1])
        self.assertFalse((self.data / "scan1" / "room_reviews.json").exists())

    def test_what_if_rejects_unknown_choices(self):
        self.assertIn("error", self.tools["what_if"].invoke({"room_id": "r1", "floor": "lava"}))
        self.assertIn("error", self.tools["what_if"].invoke({"room_id": "r1", "glass_m2": -1}))

    def test_unknown_room_is_reported_to_the_agent(self):
        with self.assertRaisesRegex(ValueError, "list_rooms"):
            self.tools["room_details"].func("r9")

    def test_approved_change_is_saved_as_a_review(self):
        result = self.tools[APPROVAL_TOOL].invoke(
            {"room_id": "r1", "surface": "floor", "value": "ceramic_tile", "reason": "Glazed tile in the photo"})
        self.assertTrue(result["saved"])
        saved = json.loads((self.data / "scan1" / "room_reviews.json").read_text())
        self.assertEqual(saved["r1"]["materials"], {"floor": "ceramic_tile"})
        self.assertEqual(self.tools["room_details"].invoke({"room_id": "r1"})["floor"], "ceramic_tile")

    def test_change_outside_choices_is_not_saved(self):
        result = self.tools[APPROVAL_TOOL].invoke(
            {"room_id": "r1", "surface": "furnishing", "value": "carpet_on_pad", "reason": "x"})
        self.assertIn("error", result)
        self.assertFalse((self.data / "scan1" / "room_reviews.json").exists())


class FakeAgent:
    """Replays graph updates the way agent.stream(..., subgraphs=True) yields them."""

    def __init__(self, updates, final="Done."):
        self.updates, self.final = updates, final

    def stream(self, payload, config, **options):
        yield from self.updates

    def get_state(self, config):
        return SimpleNamespace(values={"messages": [AIMessage(content=self.final)]})


def run(thread, payload=None):
    thread.start(payload or {"messages": []}, {"kind": "user", "text": "Which room?"})
    for _ in range(200):
        if thread.status != "running":
            return
        time.sleep(0.01)
    raise AssertionError("The agent thread did not finish")


class ThreadTests(ScanTestCase):
    def test_events_show_plan_delegation_tools_and_answer(self):
        task = AIMessage(content="", tool_calls=[{"id": "t1", "name": "task", "args": {
            "subagent_type": "acoustic-simulator", "description": "Compare fixes for r1"}}])
        updates = [
            ((), {"model": {"todos": [{"content": "List rooms", "status": "in_progress"}]}}),
            ((), {"model": {"messages": [AIMessage(content="", tool_calls=[
                {"id": "c1", "name": "list_rooms", "args": {}}])]}}),
            ((), {"model": {"messages": [task]}}),
            (("tools:t1",), {"model": {"messages": [AIMessage(content="", tool_calls=[
                {"id": "c2", "name": "what_if", "args": {"room_id": "r1", "floor": None, "ceiling": "acoustic_tile"}}])]}}),
            ((), {"tools": {"messages": [ToolMessage(content="table", tool_call_id="t1")]}}),
        ]
        thread = Thread("scan1", FakeAgent(updates, final="**r1** is best."))
        run(thread)
        kinds = [event["kind"] for event in thread.events]
        self.assertEqual(kinds, ["user", "plan", "tool", "delegate", "tool", "delegate_done", "answer"])
        sub_tool = thread.events[4]
        self.assertEqual(sub_tool["agent"], "acoustic-simulator")
        self.assertEqual(sub_tool["args"], {"room_id": "r1", "ceiling": "acoustic_tile"})
        self.assertEqual(thread.events[-1]["text"], "**r1** is best.")
        self.assertEqual(thread.status, "idle")

    def test_interrupt_waits_for_approval_with_current_label(self):
        request = {"action_requests": [{"name": APPROVAL_TOOL, "args": {
            "room_id": "r1", "surface": "floor", "value": "ceramic_tile", "reason": "Tile visible"}}],
            "review_configs": []}
        thread = Thread("scan1", FakeAgent([((), {"__interrupt__": (SimpleNamespace(value=request),)})]))
        run(thread)
        self.assertEqual(thread.status, "awaiting_approval")
        approval = thread.events[-1]
        self.assertEqual((approval["kind"], approval["current"], approval["value"]), ("approval", "vinyl_tile", "ceramic_tile"))
        self.assertTrue(approval["photo_url"].endswith("/rooms/r1/acoustics/photos/5"))

    def test_busy_thread_refuses_a_second_question(self):
        thread = Thread("scan1", FakeAgent([]))
        thread.status = "awaiting_approval"
        with self.assertRaises(Exception):
            thread.start({"messages": []})

    def test_failure_becomes_an_error_event(self):
        class Broken(FakeAgent):
            def stream(self, *args, **kwargs):
                raise RuntimeError("model down")
                yield

        thread = Thread("scan1", Broken([]))
        with self.assertLogs("app.api.agent", level="ERROR"):
            run(thread)
        self.assertEqual((thread.status, thread.events[-1]["kind"]), ("error", "error"))

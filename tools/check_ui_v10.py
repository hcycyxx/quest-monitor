"""Offline V10 checks: temporary fixtures only. No GUI, services or model calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ui"), str(ROOT / "engine")]
from v10_bridge import Bridge, progress
from quest_window_v10 import Desktop


class V10Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sidequest-v10-offline-")
        self.directory = Path(self.temp.name)
        self.path = self.directory / "quest_state.json"
        self.fixture = {"main_quests": [{"id": "M1", "title": "虚拟报价", "status": "active",
                         "priority": "high", "note": "仅离线虚拟数据",
                         "progress_range": [30, 50], "progress_basis": "虚拟依据",
                         "steps": [{"text": "核对参数", "done": True}, {"text": "确认数量", "done": False}]}],
                        "side_quests": [], "current_activity": "虚拟活动", "suggestion": "虚拟建议"}
        self.write(self.fixture)
        self.bridge = Bridge(self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, value):
        self.path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def request(self, **overrides):
        value = {"request_id": "fixture-1", "key": "main_quests", "id": "M1", "title": "虚拟报价",
                 "kind": "task", "done": True}
        value.update(overrides)
        return value

    def test_estimate_range_does_not_become_exact(self):
        value = progress(self.fixture["main_quests"][0])
        self.assertEqual((value["low"], value["high"]), (30, 50))
        self.assertIn("30–50", value["label"])
        self.assertIsNone(progress({})["low"])
        self.assertEqual(progress({"completion_candidate": True})["label"], "待确认完成")

    def test_save_deduplicate_and_undo(self):
        result = self.bridge.task_action(self.request())
        self.assertTrue(result["ok"])
        saved = self.path.read_bytes()
        self.assertTrue(self.bridge.task_action(self.request())["ok"])
        self.assertEqual(self.path.read_bytes(), saved)
        self.assertEqual(json.loads(saved)["main_quests"][0]["status"], "done")
        self.assertTrue(self.bridge.undo(result["undo"])["ok"])
        restored = json.loads(self.path.read_text(encoding="utf-8"))["main_quests"][0]
        self.assertEqual(restored, self.fixture["main_quests"][0])

    def test_reused_request_id_cannot_change_meaning(self):
        self.assertTrue(self.bridge.task_action(self.request())["ok"])
        self.assertFalse(self.bridge.task_action(self.request(done=False))["ok"])

    def test_changed_identity_and_step_are_rejected_without_writing(self):
        before = self.path.read_bytes()
        self.assertFalse(self.bridge.task_action(self.request(title="已经变化"))["ok"])
        self.assertFalse(self.bridge.task_action(self.request(kind="step", step=1, step_text="旧步骤"))["ok"])
        self.assertEqual(before, self.path.read_bytes())

    def test_step_completion_preserves_existing_manual_policy(self):
        result = self.bridge.task_action(self.request(kind="step", step=1, step_text="确认数量"))
        self.assertTrue(result["ok"])
        task = json.loads(self.path.read_text(encoding="utf-8"))["main_quests"][0]
        self.assertEqual(task["status"], "done")
        self.assertTrue(task["_user_state"]["steps"]["确认数量"])
        self.assertTrue(task["completed_at"])

    def test_undo_does_not_overwrite_newer_changes(self):
        result = self.bridge.task_action(self.request())
        current = json.loads(self.path.read_text(encoding="utf-8"))
        current["main_quests"][0]["note"] = "后来的新变化"
        self.write(current)
        before = self.path.read_bytes()
        self.assertFalse(self.bridge.undo(result["undo"])["ok"])
        self.assertEqual(before, self.path.read_bytes())

    def test_read_error_preserves_last_successful_content(self):
        self.assertEqual(self.bridge.snapshot()["current"]["title"], "虚拟报价")
        self.path.write_text("{broken", encoding="utf-8")
        snapshot = self.bridge.snapshot()
        self.assertEqual(snapshot["current"]["title"], "虚拟报价")
        self.assertIn("读取失败", snapshot["error"])

    def test_preferences_are_separate_and_whitelisted(self):
        before = self.path.read_bytes()
        result = self.bridge.preferences({"font": 19, "skin": "journal", "api_key": "never-save"})
        self.assertTrue(result["ok"])
        saved = json.loads((self.directory / "ui_v10.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["font"], 19)
        self.assertNotIn("api_key", saved)
        self.assertEqual(before, self.path.read_bytes())

    def test_damped_motion_converges_and_reverses_without_jumps(self):
        x, velocity = 0., 0.
        trace = []
        for _ in range(180):
            x, velocity = Desktop._spring(x, velocity, 300., 1/60)
            trace.append(x)
        self.assertEqual(x, 300.)
        self.assertTrue(all(a <= b for a, b in zip(trace, trace[1:])))
        self.assertLessEqual(max(trace), 300.)
        x, velocity = 180., 200.
        for _ in range(180):
            x, velocity = Desktop._spring(x, velocity, 0., 1/60)
        self.assertEqual(x, 0.)

    def test_native_geometry_uses_bounds_without_opening_window(self):
        class FakeWindow:
            native = None
            def resize(self, width, height):
                self.size = (width, height)
            def move(self, x, y):
                self.position = (x, y)
        desktop = Desktop()
        desktop._window = FakeWindow()
        desktop._screens = [{"left": 0, "top": 0, "right": 1200, "bottom": 900}]
        desktop._bridge = Bridge(self.directory, desktop)
        result = desktop.action("geometry", {"phase": "resize", "x": 100, "y": 100, "width": 420, "height": 400})
        self.assertTrue(result["ok"])
        self.assertEqual(desktop._window.size, (420, 400))
        desktop.action("geometry", {"phase": "end", "dock": False})
        desktop.action("fit", {"height": 9000})
        self.assertEqual(desktop._target_h, 400)
        self.assertTrue(desktop.action("dock", {"side": "left"})["ok"])
        self.assertEqual(desktop._target_x, 0)
        before = desktop.state()
        with self.assertLogs(level="ERROR"):
            self.assertFalse(desktop.action("geometry", {"phase": "resize", "width": float("nan")})["ok"])
        self.assertEqual(desktop.state(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)

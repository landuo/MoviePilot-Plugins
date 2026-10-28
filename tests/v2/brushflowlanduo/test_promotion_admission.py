import ast
import time
import unittest
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Set
from zoneinfo import ZoneInfo


PLUGIN_PATH = Path(__file__).parents[3] / "plugins.v2/brushflowlanduo/__init__.py"


class PromotionAdmissionTests(unittest.TestCase):
    def build(self, *, save_fails=False, stale=False):
        source = ast.parse(PLUGIN_PATH.read_text())
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "BrushFlowLanduo")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__brush_site_torrents")
        harness = ast.ClassDef(name="Harness", bases=[], keywords=[], decorator_list=[], body=[method])
        candidate = SimpleNamespace(pubdate="2026-10-28 18:04:48", title="尚公主", description="14", size=1000)
        ns = {"Any": Any, "Dict": Dict, "Set": Set, "time": time, "datetime": datetime, "timedelta": timedelta,
              "logger": SimpleNamespace(info=lambda *args: None, warning=lambda *args: None),
              "TorrentsChain": lambda: SimpleNamespace(browse=lambda **kw: [candidate]),
              "EventType": SimpleNamespace(PluginTriggered="event")}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), str(PLUGIN_PATH), "exec"), ns)
        plugin = ns["Harness"]()
        task = SimpleNamespace(id="hh", name="hh", rss_support=False, except_subscribe=False, del_no_free=True)
        plugin._get_task_config = lambda: task
        plugin._Harness__calculate_seeding_torrents_size = lambda rows: 0
        plugin._Harness__evaluate_pre_conditions_for_brush = lambda **kw: (True, None)
        plugin._Harness__evaluate_size_condition_for_brush = lambda *args, **kw: (True, None)
        plugin._Harness__evaluate_conditions_for_brush = lambda *args: (True, None)
        plugin._verify_candidate_promotion = lambda *args: True
        now = time.time()
        deadline = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(hours=2)
        plugin._torrent_to_task_record = lambda *args: {"freedate": deadline.isoformat(),
            "promotion_verified_at": now - (1800 if stale else 0)}
        plugin._resolve_promotion_expiry = lambda *args: (deadline, "")
        plugin.PROMOTION_STOP_MARGIN = 600
        plugin.PROMOTION_VERIFY_INTERVAL = 900
        calls = []
        plugin._Harness__download = lambda *args: calls.append("add_paused") or "hash"

        def save(key, rows):
            calls.append("save")
            self.assertIn("hash", rows)
            if save_fails:
                raise OSError("database unavailable")

        plugin._save_current_task_data = save
        plugin.downloader = SimpleNamespace(start_torrents=lambda **kw: calls.append("start") or True)
        plugin.service_info = SimpleNamespace(name="qb")
        plugin.eventmanager = SimpleNamespace(send_event=lambda **kw: None)
        plugin._Harness__send_add_message = lambda *args: None
        report = {"reason_counts": Counter(), "added_count": 0, "added_titles": []}
        run = lambda: plugin._Harness__brush_site_torrents(
            SimpleNamespace(name="hh", domain="hhanclub.net"), {}, {}, set(), report, 0)
        return calls, run

    def test_record_is_durable_before_download_starts(self):
        calls, run = self.build()
        run()
        self.assertEqual(calls, ["add_paused", "save", "start"])

    def test_crash_during_persistence_leaves_torrent_paused(self):
        calls, run = self.build(save_fails=True)
        with self.assertRaises(OSError):
            run()
        self.assertEqual(calls, ["add_paused", "save"])

    def test_verification_expiring_during_add_cannot_start_download(self):
        calls, run = self.build(stale=True)
        run()
        self.assertNotIn("start", calls)


if __name__ == "__main__":
    unittest.main()

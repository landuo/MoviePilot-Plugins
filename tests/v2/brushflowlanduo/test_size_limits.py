import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional, Tuple


PLUGIN_PATH = Path(__file__).parents[3] / "plugins.v2" / "brushflowlanduo" / "__init__.py"


def load_size_limit_harness():
    tree = ast.parse(PLUGIN_PATH.read_text(encoding="utf-8"))
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BrushFlowLanduo"
    )
    method_names = {
        "_calculate_global_downloader_size",
        "__bytes_to_gb",
        "__evaluate_size_condition_for_brush",
    }
    harness = ast.ClassDef(
        name="BrushFlowHarness",
        bases=[],
        keywords=[],
        decorator_list=[],
        body=[
            node for node in plugin_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names
        ],
    )
    namespace = {"Optional": Optional, "Tuple": Tuple, "DownloaderHelper": None}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), str(PLUGIN_PATH), "exec"), namespace)
    return namespace


class FakeDownloader:
    def __init__(self, torrents):
        self.torrents = torrents
        self.calls = 0

    def is_inactive(self):
        return False

    def get_torrents(self):
        self.calls += 1
        return self.torrents, None


class SizeLimitTests(unittest.TestCase):
    def setUp(self):
        self.namespace = load_size_limit_harness()
        self.plugin = self.namespace["BrushFlowHarness"]()

    def test_global_size_uses_all_actual_downloader_torrents_once(self):
        downloader = FakeDownloader([
            {"total_size": 100},
            {"total_size": 200},
        ])
        service = SimpleNamespace(instance=downloader)

        class Helper:
            def get_service(self, name):
                return service if name == "qb" else None

            @staticmethod
            def is_downloader(name, service=None):
                return name == "qbittorrent"

        self.plugin._task_configs = {
            "one": SimpleNamespace(downloader="qb"),
            "two": SimpleNamespace(downloader="qb"),
        }
        self.namespace["DownloaderHelper"] = Helper

        self.assertEqual(self.plugin._calculate_global_downloader_size(), 300)
        self.assertEqual(downloader.calls, 1)

    def test_current_size_below_limit_passes_without_predicting_candidate(self):
        gib = 1024 ** 3
        self.plugin._global_disksize = 2048
        self.plugin._get_task_config = lambda: SimpleNamespace(disksize=512)

        passed, reason = self.plugin._BrushFlowHarness__evaluate_size_condition_for_brush(
            511 * gib,
            global_torrents_size=2047 * gib,
        )

        self.assertTrue(passed)
        self.assertIsNone(reason)

    def test_current_size_at_limit_is_blocked(self):
        gib = 1024 ** 3
        self.plugin._global_disksize = 2048
        self.plugin._get_task_config = lambda: SimpleNamespace(disksize=None)

        passed, reason = self.plugin._BrushFlowHarness__evaluate_size_condition_for_brush(
            0,
            global_torrents_size=2048 * gib,
        )

        self.assertFalse(passed)
        self.assertEqual(
            reason,
            "下载器当前种子总体积 2048.0 GB，已达到全局保种上限 2048 GB",
        )


if __name__ == "__main__":
    unittest.main()

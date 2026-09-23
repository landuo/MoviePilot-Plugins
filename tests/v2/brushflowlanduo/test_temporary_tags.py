import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional, Union


REPO_ROOT = Path(__file__).parents[3]
V1_PLUGIN_PATH = REPO_ROOT / "plugins" / "brushflowlanduo" / "__init__.py"
V2_PLUGIN_PATH = REPO_ROOT / "plugins.v2" / "brushflowlanduo" / "__init__.py"


class FakeStringUtils:
    @staticmethod
    def generate_random_str(length):
        assert length == 10
        return "abcdefghij"


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)

    @staticmethod
    def error(*args, **kwargs):
        return None


class FakeQbClient:
    def __init__(self, fail_delete=False):
        self.deleted_tags = []
        self.fail_delete = fail_delete

    def torrents_delete_tags(self, tags):
        self.deleted_tags.append(tags)
        if self.fail_delete:
            raise RuntimeError("delete failed")


class FakeDownloader:
    def __init__(self, torrent_hash="hash-1", fail_delete=False):
        self.qbc = FakeQbClient(fail_delete=fail_delete)
        self.torrent_hash = torrent_hash
        self.added_tags = None

    def add_torrent(self, **kwargs):
        self.added_tags = kwargs["tag"]
        return True

    def get_torrent_id_by_tag(self, tags):
        assert tags == "abcdefghij"
        return self.torrent_hash


def load_harness(path: Path, method_names, include_global_tag=False):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BrushFlowLanduo"
    )
    body = [
        node for node in plugin_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names
    ]
    if include_global_tag:
        body = [
            node for node in plugin_class.body
            if isinstance(node, ast.Assign)
            and any(getattr(target, "id", "") == "GLOBAL_BRUSH_TAG" for target in node.targets)
        ] + body
    harness = ast.ClassDef(
        name="BrushFlowHarness",
        bases=[],
        keywords=[],
        decorator_list=[],
        body=body,
    )
    logger = FakeLogger()
    namespace = {
        "Any": Any,
        "List": List,
        "Optional": Optional,
        "Union": Union,
        "TorrentInfo": object,
        "StringUtils": FakeStringUtils,
        "RequestUtils": object,
        "settings": SimpleNamespace(PROXY=None),
        "logger": logger,
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), str(path), "exec"),
        namespace,
    )
    return namespace["BrushFlowHarness"], namespace, logger


class TemporaryTagTests(unittest.TestCase):
    @staticmethod
    def torrent():
        return SimpleNamespace(
            enclosure="magnet:?xt=urn:btih:test",
            title="test",
            site_proxy=False,
            site_cookie=None,
            site_ua=None,
            site=1,
            site_name="site",
        )

    @staticmethod
    def task():
        return SimpleNamespace(
            name="task",
            up_speed=None,
            dl_speed=None,
            site_skip_tips=False,
            save_path=None,
            qb_category=None,
            brush_tag="刷流-task",
        )

    def test_v2_deletes_temporary_global_tag_after_hash_lookup(self):
        harness, namespace, _ = load_harness(
            V2_PLUGIN_PATH,
            {"_delete_qbittorrent_tags", "_cleanup_temporary_qbittorrent_tag", "__download"},
            include_global_tag=True,
        )
        downloader = FakeDownloader()
        service = SimpleNamespace(instance=downloader)

        class Helper:
            @staticmethod
            def is_downloader(name, service=None):
                return name == "qbittorrent"

        namespace["DownloaderHelper"] = Helper
        plugin = harness()
        plugin.downloader = downloader
        plugin.service_info = service
        plugin._get_task_config = self.task

        result = plugin._BrushFlowHarness__download(self.torrent())

        self.assertEqual(result, "hash-1")
        self.assertIn("abcdefghij", downloader.added_tags)
        self.assertEqual(downloader.qbc.deleted_tags, ["abcdefghij"])

    def test_v2_deletes_temporary_tag_when_hash_lookup_fails(self):
        harness, namespace, _ = load_harness(
            V2_PLUGIN_PATH,
            {"_delete_qbittorrent_tags", "_cleanup_temporary_qbittorrent_tag", "__download"},
            include_global_tag=True,
        )
        downloader = FakeDownloader(torrent_hash=None)
        service = SimpleNamespace(instance=downloader)

        class Helper:
            @staticmethod
            def is_downloader(name, service=None):
                return name == "qbittorrent"

        namespace["DownloaderHelper"] = Helper
        plugin = harness()
        plugin.downloader = downloader
        plugin.service_info = service
        plugin._get_task_config = self.task

        self.assertIsNone(plugin._BrushFlowHarness__download(self.torrent()))
        self.assertEqual(downloader.qbc.deleted_tags, ["abcdefghij"])

    def test_v2_cleanup_failure_does_not_hide_successful_add(self):
        harness, namespace, logger = load_harness(
            V2_PLUGIN_PATH,
            {"_delete_qbittorrent_tags", "_cleanup_temporary_qbittorrent_tag", "__download"},
            include_global_tag=True,
        )
        downloader = FakeDownloader(fail_delete=True)
        service = SimpleNamespace(instance=downloader)

        class Helper:
            @staticmethod
            def is_downloader(name, service=None):
                return name == "qbittorrent"

        namespace["DownloaderHelper"] = Helper
        plugin = harness()
        plugin.downloader = downloader
        plugin.service_info = service
        plugin._get_task_config = self.task

        self.assertEqual(plugin._BrushFlowHarness__download(self.torrent()), "hash-1")
        self.assertEqual(len(logger.warnings), 1)

    def test_v1_deletes_temporary_global_tag_after_hash_lookup(self):
        harness, _, _ = load_harness(
            V1_PLUGIN_PATH,
            {"_cleanup_temporary_qbittorrent_tag", "__download"},
        )
        downloader = FakeDownloader()
        config = SimpleNamespace(
            downloader="qbittorrent",
            up_speed=None,
            dl_speed=None,
            save_path=None,
            proxy_download=False,
            brush_tag="刷流",
            qb_category=None,
            auto_qb_category=False,
            qb_first_last_piece=False,
        )
        plugin = harness()
        plugin.qb = downloader
        plugin._BrushFlowHarness__get_brush_config = lambda site_name: config
        plugin._BrushFlowHarness__qb_add_torrent = lambda **kwargs: True

        result = plugin._BrushFlowHarness__download(self.torrent())

        self.assertEqual(result, "hash-1")
        self.assertEqual(downloader.qbc.deleted_tags, ["abcdefghij"])


if __name__ == "__main__":
    unittest.main()

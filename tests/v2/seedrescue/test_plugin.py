import importlib.util
import sys
import threading
import time
import types
import unittest
from hashlib import sha1
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_DIR = Path(__file__).parents[3] / "plugins.v2" / "seedrescue"


def module(name, **attrs):
    value = types.ModuleType(name)
    for key, item in attrs.items():
        setattr(value, key, item)
    sys.modules[name] = value
    return value


class PluginBase:
    def __init__(self):
        self._data = {}
        self.messages = []

    def get_data(self, key):
        return self._data.get(key)

    def save_data(self, key, value):
        self._data[key] = value

    def update_config(self, config):
        self.saved_config = config

    def post_message(self, **kwargs):
        self.messages.append(kwargs)


class Response:
    def __init__(self, success=True, data=None, message=None):
        self.success = success
        self.data = data
        self.message = message


class CronTrigger:
    @staticmethod
    def from_crontab(value):
        if value == "bad":
            raise ValueError("bad cron")
        return ("cron", value)


class DownloaderHelper:
    service = SimpleNamespace(type="qbittorrent", instance=object())

    def get_service(self, name):
        return self.service if name else None

    def get_configs(self):
        return {}


class PluginManager:
    def get_plugin_state(self, plugin_id):
        return plugin_id == "IYUUAutoSeed"


class IyuuHelper:
    def __init__(self, token):
        self.token = token


def install_host_stubs():
    app = module("app")
    app.__path__ = []
    module("app.chain").__path__ = []
    module("app.chain.download", DownloadChain=object)
    module("app.chain.torrents", TorrentsChain=object)
    module("app.core").__path__ = []
    module("app.core.config", settings=SimpleNamespace(USER_AGENT="test-agent"))
    module("app.core.plugin", PluginManager=PluginManager)
    module("app.db").__path__ = []
    module("app.db.site_oper", SiteOper=object)
    module("app.helper").__path__ = []
    module("app.helper.downloader", DownloaderHelper=DownloaderHelper)
    module("app.helper.rss", RssHelper=object)
    module("app.helper.sites", SitesHelper=object)
    module("app.helper.torrent", TorrentHelper=object)
    module("app.log", logger=SimpleNamespace(error=lambda *args: None,
                                               warning=lambda *args: None,
                                               info=lambda *args: None))
    plugins = module("app.plugins", _PluginBase=PluginBase)
    plugins.__path__ = []
    iyuu_package = module("app.plugins.iyuuautoseed")
    iyuu_package.__path__ = []
    module("app.plugins.iyuuautoseed.iyuu_helper", IyuuHelper=IyuuHelper)
    module("app.schemas", NotificationType=SimpleNamespace(SiteMessage="site"), Response=Response)
    module("app.utils").__path__ = []
    module("app.utils.string", StringUtils=object)
    module("app.utils.http", RequestUtils=object)
    module("apscheduler").__path__ = []
    module("apscheduler.triggers").__path__ = []
    module("apscheduler.triggers.cron", CronTrigger=CronTrigger)


install_host_stubs()
SPEC = importlib.util.spec_from_file_location(
    "seedrescue_plugin_under_test",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
plugin_module = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = plugin_module
SPEC.loader.exec_module(plugin_module)


class FakeIyuu:
    def __init__(self, payload, message=""):
        self.payload = payload
        self.message = message

    def get_seed_info(self, hashes):
        return self.payload, self.message


class PluginWorkflowTests(unittest.TestCase):
    def plugin(self):
        value = plugin_module.SeedRescue()
        value._notify = False
        value._confirm_download_risk = True
        value._minimum_seeders = 10
        value._allowed_promotions = {plugin_module.FREE, plugin_module.NON_FREE}
        value._max_download_count = 2
        value._source_site_ids = [2]
        return value

    @staticmethod
    def job():
        return {
            "target_hash": "a" * 40,
            "title": "Example.Release",
            "state": "MATCHING",
            "probes": [],
        }

    def test_no_iyuu_match_is_terminal_skip(self):
        plugin = self.plugin()
        plugin._iyuu = FakeIyuu({}, "not found")
        job = self.job()
        plugin._find_and_download(job)
        self.assertEqual(job["state"], "SKIPPED_NO_IYUU_MATCH")
        self.assertEqual(job["reason"], "not found")

    def test_transient_iyuu_failure_waits_for_retry(self):
        plugin = self.plugin()
        plugin._iyuu = FakeIyuu(None, "请求IYUU失败，未获取到返回信息")
        job = self.job()

        plugin._find_and_download(job)

        self.assertEqual(job["state"], "WAITING_IYUU_RETRY")

    def test_iyuu_explicit_no_data_is_terminal_skip(self):
        plugin = self.plugin()
        plugin._iyuu = FakeIyuu(
            None,
            "请求IYUU失败，状态码：404，返回信息：未查询到可辅种数据",
        )
        job = self.job()

        plugin._find_and_download(job)

        self.assertEqual(job["state"], "SKIPPED_NO_IYUU_MATCH")

    def test_legacy_transient_skip_is_retried(self):
        plugin = self.plugin()
        job = self.job()
        job.update({
            "state": "SKIPPED_NO_IYUU_MATCH",
            "reason": "请求IYUU失败，未获取到返回信息",
        })
        retried = []
        plugin._find_and_download = lambda value: retried.append(value)

        plugin._resume_waiting_jobs({job["target_hash"]: job})

        self.assertEqual(retried, [job])

    def test_all_sources_below_minimum_are_skipped_without_download(self):
        plugin = self.plugin()
        source_hash = "b" * 40
        plugin._iyuu = FakeIyuu({"a" * 40: {"torrent": {
            "sid": 3,
            "torrent_id": 42,
            "info_hash": source_hash,
        }}})
        match = plugin_module.IyuuMatch(3, "42", source_hash)
        candidate = plugin_module.SourceCandidate(match, 2, "source", 9, 0, 0, object())
        plugin._probe_sources = lambda matches, title: ([candidate], [{"seeders": 9}])
        plugin._start_source = lambda candidate, job: self.fail("不应下载不达标来源")
        job = self.job()
        plugin._find_and_download(job)
        self.assertEqual(job["state"], "SKIPPED_NO_HEALTHY_SOURCE")
        self.assertEqual(job["probes"], [{"seeders": 9}])

    def test_manual_mode_waits_for_selection(self):
        plugin = self.plugin()
        source_hash = "b" * 40
        plugin._iyuu = FakeIyuu({"a" * 40: {"torrent": {
            "sid": 3,
            "torrent_id": 42,
            "info_hash": source_hash,
        }}})
        match = plugin_module.IyuuMatch(3, "42", source_hash)
        candidate = plugin_module.SourceCandidate(match, 2, "source", 10, 1, 0, object())
        plugin._probe_sources = lambda matches, title: ([candidate], [])
        plugin._downloading_count = lambda: 0

        plugin._start_source = lambda selected, job: self.fail("手动模式不应自动下载")
        job = self.job()
        plugin._find_and_download(job)
        self.assertEqual(job["state"], "AWAITING_SELECTION")
        self.assertEqual(job["candidates"][0]["site_id"], 2)

    def test_rejection_reason_explains_free_only_filter(self):
        plugin = self.plugin()
        plugin._allowed_promotions = {plugin_module.FREE}
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", "b" * 40),
            2,
            "source",
            6,
            1,
            0,
            object(),
        )

        reason = plugin._source_rejection_reason([candidate], [{"matched": True}])

        self.assertIn("已精确匹配 1 个", reason)
        self.assertIn("1 个非免费", reason)
        self.assertIn("当前允许：免费", reason)

    def test_batch_iyuu_request_and_parallel_job_probes(self):
        plugin = self.plugin()
        jobs = [self.job(), {**self.job(), "target_hash": "c" * 40}]
        payload = {
            jobs[0]["target_hash"]: {"torrent": {
                "sid": 3, "torrent_id": 42, "info_hash": "b" * 40,
            }},
            jobs[1]["target_hash"]: {"torrent": {
                "sid": 4, "torrent_id": 43, "info_hash": "d" * 40,
            }},
        }

        class CountingIyuu(FakeIyuu):
            def __init__(self, value):
                super().__init__(value)
                self.calls = []

            def get_seed_info(self, hashes):
                self.calls.append(list(hashes))
                return super().get_seed_info(hashes)

        plugin._iyuu = CountingIyuu(payload)
        active = 0
        max_active = 0
        guard = threading.Lock()

        def probe(matches, title):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with guard:
                active -= 1
            match = matches[0]
            candidate = plugin_module.SourceCandidate(
                match, 2, "source", 10, 1, 0, object()
            )
            return [candidate], [{"matched": True, "seeders": 10}]

        plugin._probe_sources = probe
        plugin._find_and_download_jobs(jobs)

        self.assertEqual(plugin._iyuu.calls, [["a" * 40, "c" * 40]])
        self.assertEqual(max_active, 2)
        self.assertTrue(all(job["state"] == "AWAITING_SELECTION" for job in jobs))

    def test_auto_mode_starts_download(self):
        plugin = self.plugin()
        plugin._selection_mode = "auto"
        source_hash = "b" * 40
        plugin._iyuu = FakeIyuu({"a" * 40: {"torrent": {
            "sid": 3,
            "torrent_id": 42,
            "info_hash": source_hash,
        }}})
        match = plugin_module.IyuuMatch(3, "42", source_hash)
        candidate = plugin_module.SourceCandidate(match, 2, "source", 10, 1, 0, object())
        plugin._probe_sources = lambda matches, title: ([candidate], [])
        plugin._downloading_count = lambda: 0

        def start(selected, job):
            job["state"] = "SOURCE_DOWNLOADING"
            return True, ""

        plugin._start_source = start
        job = self.job()
        plugin._find_and_download(job)
        self.assertEqual(job["state"], "SOURCE_DOWNLOADING")

    def test_probe_uses_iyuu_torrent_id_and_moviepilot_seeders(self):
        plugin = self.plugin()
        plugin._iyuu = SimpleNamespace(get_torrent_url=lambda sid: ("https://source.example", "download.php?id={torrent_id}"))
        torrent = SimpleNamespace(
            page_url="https://source.example/details.php?id=42&hit=1",
            enclosure="https://source.example/download.php?id=42",
            seeders=18,
            downloadvolumefactor=0,
        )
        plugin_module.StringUtils = SimpleNamespace(get_url_domain=lambda url: "source.example")
        plugin_module.SitesHelper = lambda: SimpleNamespace(
            get_indexer=lambda domain: {"id": 2, "name": "source"}
        )
        plugin_module.TorrentsChain = lambda: SimpleNamespace(
            browse=lambda domain, keyword, page=0: [torrent]
        )
        match = plugin_module.IyuuMatch(3, "42", "b" * 40)
        candidates, probes = plugin._probe_sources([match], "Example.Release")
        self.assertEqual(candidates[0].seeders, 18)
        self.assertEqual(candidates[0].download_factor, 0)
        self.assertTrue(probes[0]["matched"])
        self.assertEqual(probes[0]["page_url"], "https://source.example/details.php?id=42&hit=1")

    def test_refresh_target_job_adds_live_stats_and_safe_detail_link(self):
        plugin = self.plugin()
        job = self.job()
        job["target_torrent_id"] = "88"
        torrent = SimpleNamespace(
            page_url="https://target.example/details.php?id=88&passkey=secret",
            enclosure="https://target.example/download.php?id=88&passkey=secret",
            seeders=7,
            peers=3,
            grabs=25,
            size=1024,
            downloadvolumefactor=0,
        )
        plugin_module.TorrentsChain = lambda: SimpleNamespace(
            browse=lambda domain, keyword: [torrent]
        )

        plugin._refresh_target_job(job, "target.example")

        self.assertEqual(job["target_page_url"], "https://target.example/details.php?id=88")
        self.assertEqual(job["target_seeders"], 7)
        self.assertEqual(job["target_peers"], 3)
        self.assertEqual(job["target_grabs"], 25)
        self.assertEqual(job["target_size"], 1024)
        self.assertTrue(job["target_stats_updated_at"])
        self.assertEqual(job["target_download_factor"], 0)
        self.assertTrue(job["target_promotion_updated_at"])
        self.assertTrue(job["target_stats_checked_at"])
        self.assertIsNone(job["target_stats_error"])

    def test_target_refresh_keeps_last_known_promotion_when_response_omits_it(self):
        plugin = self.rss_setup()
        job = self.rss_job(88, target_download_factor=0, target_stats_updated_at="2026-09-28T20:00:00+08:00")
        torrent = SimpleNamespace(
            page_url="https://target/details.php?id=88", enclosure=None,
            seeders=7, peers=3, grabs=25, size=1024, downloadvolumefactor=None,
        )
        with patch.object(plugin_module, "TorrentsChain", lambda: SimpleNamespace(browse=lambda **kwargs: [torrent])):
            plugin._refresh_target_job(job, "target")
        self.assertEqual(job["target_download_factor"], 0)
        self.assertEqual(job["target_promotion_updated_at"], "2026-09-28T20:00:00+08:00")
        self.assertEqual(job["target_stats_updated_at"], plugin._now())
        self.assertIn("未提供有效促销", job["target_stats_error"])
        view = plugin._job_view(job)["target_candidate"]
        self.assertEqual(view["promotion"], "free")
        self.assertEqual(view["promotion_updated_at"], job["target_promotion_updated_at"])
        self.assertIn("未提供有效促销", view["promotion_note"])

    def test_target_refresh_failure_records_attempt_without_erasing_last_success(self):
        plugin = self.rss_setup()
        job = self.rss_job(88, target_download_factor=1, target_stats_updated_at="2026-09-28T20:00:00+08:00")
        with patch.object(plugin_module, "TorrentsChain", lambda: SimpleNamespace(browse=lambda **kwargs: [])):
            plugin._refresh_target_job(job, "target")
        self.assertEqual(job["target_download_factor"], 1)
        self.assertEqual(job["target_stats_updated_at"], "2026-09-28T20:00:00+08:00")
        self.assertEqual(job["target_stats_checked_at"], plugin._now())
        self.assertIn("未在原站搜索结果", job["target_stats_error"])
        self.assertEqual(plugin._select_target_refresh_jobs({job["target_hash"]: job}), [])

    def test_target_refresh_exception_is_safe_and_does_not_starve_other_jobs(self):
        plugin = self.rss_setup()
        job = self.rss_job(88)
        with patch.object(plugin_module, "TorrentsChain", lambda: SimpleNamespace(
            browse=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("passkey=secret")),
        )):
            plugin._refresh_target_jobs([job], SimpleNamespace(domain="target"))
        self.assertEqual(job["target_stats_checked_at"], plugin._now())
        self.assertIn("查询失败", job["target_stats_error"])
        self.assertNotIn("secret", str(plugin._job_view(job)))
        self.assertEqual(plugin._select_target_refresh_jobs({job["target_hash"]: job}), [])

    def test_probe_parallelizes_different_source_domains(self):
        plugin = self.plugin()
        plugin._source_site_ids = [2, 3]
        plugin._iyuu = SimpleNamespace(
            get_torrent_url=lambda sid: (f"https://source{sid}.example", "download.php?id={}")
        )
        plugin_module.StringUtils = SimpleNamespace(
            get_url_domain=lambda url: url.split("//", 1)[1]
        )
        plugin_module.SitesHelper = lambda: SimpleNamespace(
            get_indexer=lambda domain: {
                "id": 2 if domain == "source3.example" else 3,
                "name": domain,
            }
        )
        active = 0
        max_active = 0
        guard = threading.Lock()

        def browse(domain, keyword, page=0):
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with guard:
                active -= 1
            torrent_id = "42" if domain == "source3.example" else "43"
            return [SimpleNamespace(
                page_url=f"https://{domain}/details.php?id={torrent_id}",
                enclosure=None,
                seeders=5,
                downloadvolumefactor=1,
            )]

        plugin_module.TorrentsChain = lambda: SimpleNamespace(browse=browse)
        matches = [
            plugin_module.IyuuMatch(3, "42", "b" * 40),
            plugin_module.IyuuMatch(4, "43", "c" * 40),
        ]

        candidates, _ = plugin._probe_sources(matches, "Movie.Name.2024.1080p")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(max_active, 2)

    def test_start_source_verifies_hash_and_adds_only_one_rescue_tag(self):
        plugin = self.plugin()
        info = b"d6:lengthi100e4:name11:example.mkve"
        content = b"d8:announce14:https://t.test4:info" + info + b"e"
        source_hash = sha1(info).hexdigest()
        torrent = SimpleNamespace(
            enclosure="https://source/download?id=42",
            site_cookie="cookie",
            site_ua="ua",
            site_proxy=False,
        )
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", source_hash),
            2,
            "source",
            12,
            0,
            0,
            torrent,
        )
        calls = []
        downloader = SimpleNamespace(add_torrent=lambda **kwargs: calls.append(kwargs) or True)
        DownloaderHelper.service = SimpleNamespace(type="qbittorrent", instance=downloader)
        plugin_module.TorrentHelper = lambda: SimpleNamespace(
            download_torrent=lambda **kwargs: (None, content, "", [], "")
        )
        plugin._downloader_name = "qb"
        plugin._save_path = "/downloads/rescue"
        plugin._get_torrent = lambda info_hash: None
        job = self.job()
        success, reason = plugin._start_source(candidate, job)
        self.assertTrue(success, reason)
        self.assertEqual(job["source_hash"], source_hash)
        self.assertEqual(job["state"], "SOURCE_DOWNLOADING")
        self.assertEqual(calls[0]["tag"], ["seed-rescue"])
        self.assertEqual(calls[0]["download_dir"], "/downloads/rescue")

    def test_start_source_resolves_indirect_mteam_download(self):
        plugin = self.plugin()
        info = b"d6:lengthi100e4:name11:example.mkve"
        content = b"d8:announce14:https://t.test4:info" + info + b"e"
        source_hash = sha1(info).hexdigest()
        torrent = SimpleNamespace(
            enclosure="[encoded-params]https://api.m-team.cc/api/torrent/genDlToken",
            site_cookie=None,
            site_ua="ua",
            site_proxy=False,
        )
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", source_hash),
            2,
            "馒头",
            12,
            1,
            0,
            torrent,
        )
        plugin_module.DownloadChain = lambda: SimpleNamespace(
            download_torrent=lambda value: (content, "", [])
        )
        plugin_module.TorrentHelper = lambda: SimpleNamespace(
            download_torrent=lambda **kwargs: self.fail("动态链接不应直接交给 TorrentHelper")
        )
        calls = []
        downloader = SimpleNamespace(add_torrent=lambda **kwargs: calls.append(kwargs) or True)
        DownloaderHelper.service = SimpleNamespace(type="qbittorrent", instance=downloader)
        plugin._downloader_name = "qb"
        plugin._save_path = "/downloads/rescue"
        plugin._get_torrent = lambda info_hash: None

        success, reason = plugin._start_source(candidate, self.job())

        self.assertTrue(success, reason)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["content"], content)
        self.assertEqual(calls[0]["tag"], ["seed-rescue"])

    def test_start_source_rejects_hash_mismatch(self):
        plugin = self.plugin()
        content = b"d4:infod6:lengthi1e4:name1:xee"
        torrent = SimpleNamespace(
            enclosure="https://source/download?id=42",
            site_cookie=None,
            site_ua=None,
            site_proxy=False,
        )
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", "b" * 40),
            2,
            "source",
            12,
            0,
            0,
            torrent,
        )
        plugin_module.TorrentHelper = lambda: SimpleNamespace(
            download_torrent=lambda **kwargs: (None, content, "", [], "")
        )
        plugin._downloader_name = "qb"
        plugin._save_path = None
        plugin._get_torrent = lambda info_hash: None
        success, reason = plugin._start_source(candidate, self.job())
        self.assertFalse(success)
        self.assertIn("Hash", reason)

    def test_start_source_honors_qbittorrent_tuple_failure(self):
        plugin = self.plugin()
        info = b"d6:lengthi100e4:name11:example.mkve"
        content = b"d8:announce14:https://t.test4:info" + info + b"e"
        source_hash = sha1(info).hexdigest()
        torrent = SimpleNamespace(
            enclosure="https://source/download?id=42",
            site_cookie=None,
            site_ua=None,
            site_proxy=False,
        )
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", source_hash),
            2,
            "source",
            12,
            0,
            0,
            torrent,
        )
        downloader = SimpleNamespace(add_torrent=lambda **kwargs: (False, []))
        DownloaderHelper.service = SimpleNamespace(type="qbittorrent", instance=downloader)
        plugin_module.TorrentHelper = lambda: SimpleNamespace(
            download_torrent=lambda **kwargs: (None, content, "", [], "")
        )
        plugin._downloader_name = "qb"
        plugin._save_path = None
        plugin._get_torrent = lambda info_hash: None

        job = self.job()
        with self.assertRaises(plugin_module.DownloadSubmissionUncertain):
            plugin._start_source(candidate, job)
        self.assertEqual(job["state"], "SOURCE_SUBMITTING")
        self.assertIn("未确认", job["reason"])

    def test_reconcile_marks_known_target_complete(self):
        plugin = self.plugin()
        plugin._get_torrent = lambda info_hash: {"progress": 1, "state": "uploading"} if info_hash == "a" * 40 else None
        job = self.job()
        job.update({"state": "WAITING_IYUU", "source_hash": "b" * 40})
        plugin._reconcile_jobs({job["target_hash"]: job})
        self.assertEqual(job["state"], "TARGET_SEEDING")

    def test_scan_persists_strict_skip_and_deduplicates_rss_item(self):
        plugin = self.plugin()
        plugin._data = {}
        plugin._lock = __import__("threading").Lock()
        plugin._rss_urls = ["https://target/rss?passkey=secret"]
        plugin._initial_limit = 20
        plugin._target_site_id = 1
        plugin._valid_config = lambda log_error=False: True
        plugin._reconcile_jobs = lambda jobs: None
        plugin._resume_waiting_jobs = lambda jobs: None
        info = b"d6:lengthi100e4:name11:example.mkve"
        content = b"d8:announce14:https://t.test4:info" + info + b"e"
        target_hash = sha1(info).hexdigest()
        source_hash = "b" * 40
        plugin._iyuu = FakeIyuu({target_hash: {"torrent": {
            "sid": 3,
            "torrent_id": 42,
            "info_hash": source_hash,
        }}})
        low_source = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", source_hash), 2, "source", 9, 0, 0, object()
        )
        plugin._probe_sources = lambda matches, title: ([low_source], [{"site_name": "source", "seeders": 9}])
        target_site = SimpleNamespace(proxy=False, timeout=30, ua="ua", cookie="cookie")
        plugin_module.SiteOper = lambda: SimpleNamespace(get=lambda site_id: target_site)
        plugin_module.RssHelper = lambda: SimpleNamespace(parse=lambda *args, **kwargs: [{
            "title": "Example.Release",
            "enclosure": "https://target/download?id=1&passkey=secret",
            "link": "https://target/details?id=1",
        }])
        downloads = []

        def download_torrent(**kwargs):
            downloads.append(kwargs["url"])
            return None, content, "", [], ""

        plugin_module.TorrentHelper = lambda: SimpleNamespace(download_torrent=download_torrent)
        plugin.scan()
        plugin.scan()
        jobs = plugin.get_data(plugin.JOBS_KEY)
        self.assertEqual(jobs[target_hash]["state"], "SKIPPED_NO_HEALTHY_SOURCE")
        self.assertEqual(len(downloads), 1)
        self.assertNotIn("secret", jobs[target_hash]["feed_key"])

    def test_run_once_registers_date_service_and_resets_config(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({
            "onlyonce": True,
            "token": "token",
            "target_site_id": 1,
            "rss_urls": "https://target/rss",
            "source_site_ids": [2],
            "allowed_promotions": [plugin_module.FREE],
            "downloader": "qb",
        })
        services = plugin.get_service()
        self.assertEqual([item["id"] for item in services], ["SeedRescue.RunOnce"])
        self.assertFalse(plugin.saved_config["onlyonce"])

    def test_reinitializing_plugin_keeps_scan_lock(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({})
        original_lock = plugin._lock

        plugin.init_plugin({})

        self.assertIs(plugin._lock, original_lock)

    def test_blank_limits_stay_unlimited_across_config_roundtrip(self):
        keys = ("minimum_seeders", "max_download_count", "initial_limit")
        for value in (None, "", "  ", 0, "0", " 0 "):
            with self.subTest(value=value):
                plugin = plugin_module.SeedRescue()
                plugin.init_plugin(dict.fromkeys(keys, value))
                config = plugin._current_config()
                self.assertTrue(all(config[key] is None for key in keys))
                plugin.init_plugin(config)
                self.assertTrue(all(plugin._current_config()[key] is None for key in keys))
        plugin.init_plugin({})
        self.assertTrue(all(plugin._current_config()[key] is None for key in keys))

    def test_explicit_limits_are_preserved_and_invalid_values_are_not_unlimited(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({"minimum_seeders": "5", "max_download_count": 100, "initial_limit": "20"})
        config = plugin._current_config()
        self.assertEqual([config[key] for key in ("minimum_seeders", "max_download_count", "initial_limit")], [5, 100, 20])
        for value in (-1, "invalid", 1.5, float("inf"), False):
            with self.subTest(value=value):
                plugin.init_plugin({key: value for key in ("minimum_seeders", "max_download_count", "initial_limit")})
                self.assertEqual((plugin._minimum_seeders, plugin._max_download_count, plugin._initial_limit), (1, 2, 20))

    def test_unlimited_capacity_skips_count_and_finite_limits_fail_closed(self):
        plugin = self.plugin()
        plugin._max_download_count = None
        plugin._downloading_count = lambda: self.fail("未设置上限时不应查询或比较任务数量")
        self.assertFalse(plugin._at_download_capacity())
        plugin._max_download_count = 3
        for count, reached in ((2, False), (3, True), (100, True), (None, True)):
            with self.subTest(count=count):
                plugin._downloading_count = lambda: count
                self.assertEqual(plugin._at_download_capacity(), reached)

    def test_auto_and_manual_sources_allow_download_when_capacity_is_unlimited(self):
        plugin = self.plugin()
        plugin._lock = threading.Lock()
        plugin._max_download_count = None
        plugin._downloading_count = lambda: self.fail("无限制时不应读取下载数")
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", "b" * 40), 2, "source", 10, 0, 0, object(),
        )
        started = []

        def start(value, job):
            started.append(value)
            job["state"] = "SOURCE_DOWNLOADING"
            return True, ""

        plugin._start_source = start
        plugin._probe_sources = lambda *args: ([candidate], [])
        auto_job = self.job()
        plugin._selection_mode = "auto"
        plugin._apply_candidates(auto_job, [candidate], [])
        self.assertEqual(auto_job["state"], "SOURCE_DOWNLOADING")
        manual_job = self.job()
        plugin._selection_mode = "manual"
        plugin._apply_candidates(manual_job, [candidate], [])
        plugin._data[plugin.JOBS_KEY] = {manual_job["target_hash"]: manual_job}
        response = plugin.download_candidate(manual_job["target_hash"], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._candidate_id(candidate)))
        self.assertTrue(response.success, response.message)
        self.assertEqual(len(started), 2)

    def test_unlimited_minimum_rejection_reason_does_not_claim_a_seeder_threshold(self):
        plugin = self.plugin()
        plugin._minimum_seeders = None
        plugin._allowed_promotions = {plugin_module.FREE}
        candidate = plugin_module.SourceCandidate(
            plugin_module.IyuuMatch(3, "42", "b" * 40), 2, "source", None, 1, 0, object(),
        )
        reason = plugin._source_rejection_reason([candidate], [{"matched": True}])
        self.assertNotIn("最少", reason)
        self.assertIn("非免费", reason)

    def test_waiting_capacity_retries_all_jobs_when_unlimited(self):
        plugin = self.plugin()
        plugin._max_download_count = None
        plugin._downloading_count = lambda: self.fail("无限制时不应读取下载数")
        jobs = {str(index): {**self.job(), "state": "WAITING_CAPACITY"} for index in range(3)}
        retried = []
        plugin._find_and_download = lambda job: retried.append(job)
        plugin._resume_waiting_jobs(jobs)
        self.assertEqual(len(retried), 3)

    def test_explicit_empty_promotions_do_not_fall_back_to_both(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({
            "enabled": True,
            "token": "token",
            "target_site_id": 1,
            "rss_urls": "https://target/rss",
            "source_site_ids": [2],
            "allowed_promotions": [],
            "downloader": "qb",
        })
        self.assertEqual(plugin._allowed_promotions, set())
        self.assertEqual(plugin.get_service(), [])

    def test_vue_form_returns_config_model(self):
        original_sites_helper = plugin_module.SitesHelper
        plugin_module.SitesHelper = lambda: SimpleNamespace(get_indexers=lambda: [])
        self.addCleanup(setattr, plugin_module, "SitesHelper", original_sites_helper)

        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({})
        form, config = plugin.get_form()
        self.assertEqual(form, [])
        self.assertEqual(config["allowed_promotions"], [plugin_module.FREE, plugin_module.NON_FREE])
        self.assertEqual(config["selection_mode"], "manual")
        self.assertEqual(plugin.get_render_mode(), ("vue", "dist/assets"))

    def test_frontend_apis_require_bearer_auth(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({})
        apis = plugin.get_api()
        self.assertEqual(
            {item["path"] for item in apis},
            {
                "/status",
                "/scan",
                "/jobs/{target_hash}",
                "/jobs/{target_hash}/download",
                "/jobs/{target_hash}/retry",
                "/jobs/{target_hash}/ignore",
            },
        )
        self.assertTrue(all(item["auth"] == "bear" for item in apis))

    def test_manual_scan_rejects_incomplete_config(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({})
        response = plugin.scan_now()
        self.assertFalse(response.success)
        self.assertIn("配置", response.message)

    def test_download_candidate_revalidates_server_side_candidate(self):
        plugin = self.plugin()
        plugin._lock = __import__("threading").Lock()
        source_hash = "b" * 40
        match = plugin_module.IyuuMatch(3, "42", source_hash)
        candidate = plugin_module.SourceCandidate(match, 2, "source", 15, 0, 0, object())
        candidate_id = plugin._candidate_id(candidate)
        job = self.job()
        job.update({
            "state": "AWAITING_SELECTION",
            "candidates": [{
                "candidate_id": candidate_id,
                "iyuu_sid": 3,
                "site_id": 2,
                "torrent_id": "42",
                "expected_hash": source_hash,
            }],
            "selected_candidate_id": None,
        })
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job}
        plugin._downloading_count = lambda: 0
        plugin._probe_sources = lambda matches, title: ([candidate], [])

        def start(selected, selected_job):
            selected_job["state"] = "SOURCE_DOWNLOADING"
            return True, ""

        plugin._start_source = start
        response = plugin.download_candidate(
            job["target_hash"],
            plugin_module.CandidateSelectionPayload(candidate_id=candidate_id),
        )
        self.assertTrue(response.success)
        self.assertEqual(job["state"], "SOURCE_DOWNLOADING")
        self.assertEqual(job["selected_candidate_id"], candidate_id)

    def test_download_candidate_rejects_unknown_candidate(self):
        plugin = self.plugin()
        plugin._lock = __import__("threading").Lock()
        job = self.job()
        job.update({"state": "AWAITING_SELECTION", "candidates": []})
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job}
        response = plugin.download_candidate(
            job["target_hash"],
            plugin_module.CandidateSelectionPayload(candidate_id="forged"),
        )
        self.assertFalse(response.success)
        self.assertIn("不存在", response.message)

    def target_download_setup(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({
            "notify": False,
            "target_site_id": 1,
            "rss_urls": "https://target.example/rss?passkey=secret",
            "source_site_ids": [2],
            "minimum_seeders": 10,
            "max_download_count": 2,
            "allowed_promotions": [plugin_module.FREE],
            "downloader": "qb",
            "save_path": "/downloads/rescue",
        })
        content = b"d4:infod6:lengthi1e4:name1:xee"
        target_hash = plugin_module.info_hash_from_torrent(content)
        job = {
            **self.job(),
            "target_hash": target_hash,
            "target_site_id": 1,
            "target_site_name": "目标站",
            "target_torrent_id": "88",
            "state": "SKIPPED_NO_IYUU_MATCH",
        }
        plugin._data[plugin.JOBS_KEY] = {target_hash: job}
        plugin._get_torrent = lambda info_hash: None
        plugin._downloading_count = lambda: 0
        plugin._probe_sources = lambda *args: self.fail("原种下载不应依赖 IYUU 或来源站")
        site = SimpleNamespace(id=1, name="目标站", domain="target.example", cookie="cookie")
        torrent = SimpleNamespace(
            page_url="https://target.example/details.php?id=88&passkey=secret",
            enclosure="https://target.example/download.php?id=88&passkey=secret",
            seeders=0, peers=3, grabs=25, size=1024, downloadvolumefactor=1,
            site_cookie="cookie", site_ua="ua", site_proxy=False,
        )
        calls = []
        overrides = [
            (plugin_module, "SiteOper", lambda: SimpleNamespace(get=lambda site_id: site)),
            (plugin_module, "TorrentsChain", lambda: SimpleNamespace(browse=lambda **kwargs: [torrent])),
            (plugin_module, "TorrentHelper", lambda: SimpleNamespace(
                download_torrent=lambda **kwargs: (None, content, "", [], ""))),
            (DownloaderHelper, "service", SimpleNamespace(type="qbittorrent", instance=SimpleNamespace(
                add_torrent=lambda **kwargs: calls.append(kwargs) or (True, [target_hash])))),
        ]
        for target, name, value in overrides:
            mock = patch.object(target, name, value)
            mock.start()
            self.addCleanup(mock.stop)
        return plugin, job, calls

    def test_target_option_available_without_cross_site_match_and_hides_credentials(self):
        plugin, job, _ = self.target_download_setup()
        job["target_page_url"] = "https://target.example/details.php?id=88&passkey=secret"
        view = plugin._job_view(job)
        self.assertTrue(view["target_candidate"]["selectable"])
        self.assertTrue(view["target_candidate"]["is_target"])
        self.assertEqual(view["target_candidate"]["page_url"], "https://target.example/details.php?id=88")
        self.assertNotIn("target_candidate", job)
        self.assertFalse(job.get("candidates"))

    def test_manual_target_download_bypasses_cross_site_filters_and_is_idempotent(self):
        plugin, job, calls = self.target_download_setup()
        selection = plugin_module.CandidateSelectionPayload(candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1)
        for state in sorted(plugin.TARGET_SELECTABLE_STATES):
            with self.subTest(state=state):
                job.update(state=state, selected_candidate_id=None, source_hash=None)
                before = len(calls)
                response = plugin.download_candidate(job["target_hash"], selection)
                self.assertTrue(response.success, response.message)
                self.assertEqual(job["state"], "TARGET_DOWNLOADING")
                self.assertEqual(job["source_hash"], job["target_hash"])
                self.assertEqual(job["source_site_id"], 1)
                self.assertEqual(job["source_seeders"], 0)
                self.assertEqual(job["promotion"], plugin_module.NON_FREE)
                self.assertEqual(job["selected_candidate_id"], selection.candidate_id)
                self.assertEqual(calls[-1]["download_dir"], "/downloads/rescue")
                self.assertEqual(calls[-1]["tag"], ["seed-rescue"])
                self.assertTrue(plugin.download_candidate(job["target_hash"], selection).success)
                self.assertEqual(len(calls), before + 1)

    def test_target_download_rejects_wrong_hash(self):
        plugin, job, calls = self.target_download_setup()
        with patch.object(plugin_module, "TorrentHelper", lambda: SimpleNamespace(
            download_torrent=lambda **kwargs: (None, b"d4:infod6:lengthi2e4:name1:xee", "", [], ""),
        )):
            response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
                candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1))
        self.assertFalse(response.success)
        self.assertIn("Hash", response.message)
        self.assertEqual(job["state"], "FAILED_TARGET_TORRENT")
        self.assertEqual(calls, [])

    def test_target_download_respects_capacity_and_rejects_another_target_identity(self):
        plugin, job, calls = self.target_download_setup()
        job["state"] = "AWAITING_SELECTION"
        response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
            candidate_id=f"target:2:{job['target_hash']}"))
        self.assertFalse(response.success)
        plugin._downloading_count = lambda: plugin._max_download_count
        response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job)))
        self.assertFalse(response.success)
        self.assertIn("上限", response.message)
        self.assertEqual(calls, [])

    def test_target_download_with_blank_capacity_is_unlimited(self):
        plugin, job, calls = self.target_download_setup()
        config = plugin._current_config()
        config["max_download_count"] = ""
        plugin.init_plugin(config)
        plugin._downloading_count = lambda: self.fail("无限制时不应读取下载数")
        response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1))
        self.assertTrue(response.success, response.message)
        self.assertEqual(len(calls), 1)

    def test_existing_target_reused_even_at_capacity_and_blocks_source_switch(self):
        plugin, job, calls = self.target_download_setup()
        plugin._get_torrent = lambda info_hash: {"progress": 1, "state": "uploading"}
        plugin._downloading_count = lambda: plugin._max_download_count
        response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job)))
        self.assertTrue(response.success)
        self.assertEqual(job["state"], "TARGET_SEEDING")
        self.assertEqual(calls, [])
        response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
            candidate_id="another-source"))
        self.assertFalse(response.success)
        self.assertNotIn(job["state"], plugin.TARGET_SELECTABLE_STATES)

    def test_direct_target_reconciles_without_waiting_for_iyuu(self):
        plugin, job, _ = self.target_download_setup()
        job.update(state="TARGET_DOWNLOADING", source_hash=job["target_hash"], source_site_id=1)
        plugin._get_torrent = lambda info_hash: {"progress": 0.5}
        plugin._reconcile_jobs({job["target_hash"]: job})
        self.assertEqual(job["state"], "TARGET_DOWNLOADING")
        plugin._get_torrent = lambda info_hash: {"progress": 1, "state": "uploading"}
        plugin._reconcile_jobs({job["target_hash"]: job})
        self.assertEqual(job["state"], "TARGET_SEEDING")

    def test_legacy_target_download_recovers_from_matching_rss_entry(self):
        plugin, job, calls = self.target_download_setup()
        job.pop("target_torrent_id")
        enclosure = "https://target.example/download.php?id=88&passkey=secret"
        job["feed_key"] = plugin_module.feed_key(enclosure, None, None)
        original_id = plugin._target_candidate_id(job)
        with patch.object(plugin_module, "RssHelper", lambda: SimpleNamespace(parse=lambda *args, **kwargs: [
            {"title": job["title"], "enclosure": "https://target.example/download.php?id=99"},
            {"title": job["title"], "enclosure": enclosure, "link": "https://target.example/details.php?id=88"},
        ])):
            response = plugin.download_candidate(job["target_hash"], plugin_module.CandidateSelectionPayload(
                candidate_id=original_id, confirm_unknown=True))
        self.assertTrue(response.success, response.message)
        self.assertEqual(job["target_torrent_id"], "88")
        self.assertEqual(job["selected_candidate_id"], original_id)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret", str(response.data))

    def rss_setup(self):
        plugin = plugin_module.SeedRescue()
        plugin.init_plugin({
            "enabled": True,
            "notify": False,
            "target_site_id": 1,
            "rss_urls": ["https://target/rss?passkey=secret"],
            "initial_limit": 1,
        })
        plugin._frontend_options = lambda: {}
        plugin._now = lambda: "2026-09-28T23:00:00+08:00"
        return plugin

    def rss_job(self, number, **fields):
        return {
            **self.job(),
            "target_hash": f"{number:040x}",
            "target_site_id": 1,
            "target_torrent_id": str(number),
            "feed_key": plugin_module.feed_key(f"https://target/download?id={number}", None, None),
            "created_at": "2026-09-22T20:00:00+08:00",
            **fields,
        }

    @staticmethod
    def rss_snapshot(ids, timestamp="2026-09-28T23:00:00+08:00"):
        return {
            "last_success_at": timestamp,
            "last_attempt_at": timestamp,
            "item_keys": [],
            "torrent_ids": [str(value) for value in ids],
            "error": None,
        }

    def test_target_refresh_prioritizes_missing_fields_beyond_rss_first_batch(self):
        plugin = self.rss_setup()
        known = self.rss_job(1, rss_current=True, target_download_factor=0,
                             target_stats_updated_at="2026-09-28T20:00:00+08:00")
        missing = self.rss_job(2, rss_current=True, target_stats_updated_at="2026-09-28T22:30:00+08:00")
        jobs = {job["target_hash"]: job for job in (known, missing)}
        self.assertEqual(plugin._select_target_refresh_jobs(jobs), [missing])
        missing.update(target_stats_checked_at=plugin._now(), target_stats_error="失败")
        self.assertEqual(plugin._select_target_refresh_jobs(jobs), [known])

    def test_target_refresh_rotates_history_and_current_records_with_one_global_budget(self):
        plugin = self.rss_setup()
        history = self.rss_job(1, rss_current=False, target_download_factor=0,
                               target_stats_checked_at="2026-09-28T21:00:00+08:00")
        current = self.rss_job(2, rss_current=True, target_download_factor=0,
                               target_stats_checked_at="2026-09-28T22:00:00+08:00")
        jobs = {job["target_hash"]: job for job in (current, history)}
        self.assertEqual(plugin._select_target_refresh_jobs(jobs), [history])
        history["target_stats_checked_at"] = plugin._now()
        self.assertEqual(plugin._select_target_refresh_jobs(jobs), [current])

    def test_target_refresh_cooldown_and_identity_checks(self):
        plugin = self.rss_setup()
        plugin._initial_limit = 10
        failed = self.rss_job(1, target_stats_checked_at="2026-09-28T22:15:00+08:00", target_stats_error="失败")
        fresh = self.rss_job(2, target_download_factor=0, target_stats_updated_at="2026-09-28T22:45:00+08:00")
        foreign = self.rss_job(3, target_site_id=2)
        legacy = self.rss_job(4, target_torrent_id=None, target_page_url="https://target/details.php?id=4")
        no_identity = self.rss_job(5, target_torrent_id=None)
        jobs = {job["target_hash"]: job for job in (failed, fresh, foreign, legacy, no_identity)}
        self.assertEqual(plugin._select_target_refresh_jobs(jobs), [legacy])
        self.assertEqual(legacy["target_torrent_id"], "4")
        self.assertIn("缺少原站种子 ID", plugin._job_view(no_identity)["target_candidate"]["promotion_note"])
        plugin._now = lambda: "2026-09-29T00:00:00+08:00"
        self.assertIn(failed, plugin._select_target_refresh_jobs(jobs))

    def test_unlimited_initial_limit_processes_all_rss_entries_and_due_metadata(self):
        plugin = self.rss_setup()
        plugin._initial_limit = None
        plugin._valid_config = lambda log_error=False: True
        plugin._reconcile_jobs = lambda jobs: None
        plugin._resume_waiting_jobs = lambda jobs: None
        plugin._find_and_download_jobs = lambda jobs: None
        refreshed = []
        plugin._refresh_target_jobs = lambda jobs, site: refreshed.extend(jobs)
        plugin._create_job = lambda item, key, site: self.rss_job(int(plugin_module.extract_torrent_id(item["link"])))
        items = [{"title": f"Torrent {number}", "link": f"https://target/details.php?id={number}"}
                 for number in range(1, 26)]
        with patch.object(plugin_module, "SiteOper", lambda: SimpleNamespace(get=lambda _: SimpleNamespace(name="target"))), \
                patch.object(plugin_module, "RssHelper", lambda: SimpleNamespace(parse=lambda *args, **kwargs: items)):
            plugin.scan()
        self.assertEqual(len(plugin.get_data(plugin.JOBS_KEY)), 25)
        self.assertEqual(len(refreshed), 25)

    def test_scan_backfills_promotion_for_records_past_initial_limit_and_in_history(self):
        plugin = self.rss_setup()
        plugin._valid_config = lambda log_error=False: True
        plugin._reconcile_jobs = lambda jobs: None
        plugin._resume_waiting_jobs = lambda jobs: None
        first = self.rss_job(1, target_download_factor=0, target_stats_updated_at=plugin._now())
        later = self.rss_job(2, target_stats_updated_at="2026-09-28T22:30:00+08:00")
        history = self.rss_job(3, target_stats_updated_at="2026-09-28T22:40:00+08:00")
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job for job in (first, later, history)}
        refreshed = []

        def refresh(jobs, site):
            refreshed.extend(job["target_torrent_id"] for job in jobs)
            for job in jobs:
                job.update(target_download_factor=0, target_stats_checked_at=plugin._now())

        plugin._refresh_target_jobs = refresh
        items = [{"title": f"Torrent {number}", "link": f"https://target/details.php?id={number}"}
                 for number in (1, 2)]
        with patch.object(plugin_module, "SiteOper", lambda: SimpleNamespace(get=lambda _: SimpleNamespace(name="target"))), \
                patch.object(plugin_module, "RssHelper", lambda: SimpleNamespace(parse=lambda *args, **kwargs: items)):
            plugin.scan()
            plugin.scan()
        self.assertEqual(refreshed, ["2", "3"])
        self.assertTrue(later["rss_current"])
        self.assertFalse(history["rss_current"])
        self.assertEqual(history["target_download_factor"], 0)

    def test_rss_membership_moves_out_and_back_without_changing_download_state(self):
        plugin = self.rss_setup()
        source_key = plugin._rss_source_keys()[0]
        job = self.rss_job(1, state="TARGET_DOWNLOADING")
        jobs = {job["target_hash"]: job}
        plugin._update_rss_presence(jobs, {source_key: self.rss_snapshot([1])})
        self.assertTrue(job["rss_current"])
        first_seen = job["rss_last_seen_at"]
        plugin._now = lambda: "2026-09-28T23:30:00+08:00"
        plugin._update_rss_presence(jobs, {source_key: self.rss_snapshot([])})
        self.assertFalse(job["rss_current"])
        self.assertEqual(job["rss_last_seen_at"], first_seen)
        self.assertEqual(job["rss_archived_at"], plugin._now())
        plugin._update_rss_presence(jobs, {source_key: self.rss_snapshot([1], plugin._now())})
        self.assertTrue(job["rss_current"])
        self.assertIsNone(job["rss_archived_at"])
        self.assertEqual(job["state"], "TARGET_DOWNLOADING")
        self.assertEqual(len(jobs), 1)

    def test_multiple_rss_keep_membership_from_failed_feed_snapshot(self):
        plugin = self.rss_setup()
        plugin._rss_urls.append("https://target/other-rss?passkey=secret")
        first, second = plugin._rss_source_keys()
        a, b, overlapping = self.rss_job(1), self.rss_job(2), self.rss_job(3)
        jobs = {job["target_hash"]: job for job in (a, b, overlapping)}
        snapshots = {first: self.rss_snapshot([1, 3]), second: self.rss_snapshot([2, 3])}
        plugin._update_rss_presence(jobs, snapshots)
        snapshots[first] = self.rss_snapshot([])
        snapshots[second]["error"] = "RSS 拉取失败"
        plugin._update_rss_presence(jobs, snapshots)
        self.assertFalse(a["rss_current"])
        self.assertTrue(b["rss_current"])
        self.assertTrue(overlapping["rss_current"])
        plugin._data[plugin.JOBS_KEY] = jobs
        plugin._data[plugin.RSS_SNAPSHOTS_KEY] = snapshots
        response = plugin.get_status()
        self.assertEqual(response.data["rss_status"]["failed_feeds"], 1)

    def test_missing_first_snapshot_keeps_existing_classification_and_marks_legacy_unconfirmed(self):
        plugin = self.rss_setup()
        current = self.rss_job(1, rss_current=True)
        legacy = self.rss_job(2)
        jobs = {job["target_hash"]: job for job in (current, legacy)}
        plugin._update_rss_presence(jobs, {plugin._rss_source_keys()[0]: {"error": "失败"}})
        self.assertTrue(current["rss_current"])
        self.assertNotIn("rss_current", legacy)
        plugin._data[plugin.JOBS_KEY] = jobs
        response = plugin.get_status(view="history")
        self.assertEqual(response.data["summary"]["unclassified"], 1)
        self.assertEqual([job["target_hash"] for job in response.data["jobs"]], [legacy["target_hash"]])

    def test_current_and_history_pagination_are_disjoint_and_reach_beyond_100(self):
        plugin = self.rss_setup()
        jobs = [self.rss_job(number, rss_current=number <= 5) for number in range(1, 131)]
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job for job in jobs}
        current = plugin.get_status().data
        self.assertEqual(current["summary"]["current"], 5)
        self.assertEqual(current["summary"]["history"], 125)
        self.assertEqual(current["view_summary"]["total"], 5)
        seen = {job["target_hash"] for job in current["jobs"]}
        for page in range(1, 8):
            history = plugin.get_status(view="history", page=page).data
            self.assertEqual(history["pagination"]["pages"], 7)
            hashes = {job["target_hash"] for job in history["jobs"]}
            self.assertFalse(seen & hashes)
            seen |= hashes
        self.assertEqual(len(seen), 130)
        self.assertEqual(plugin.get_status(view="history", page=99).data["pagination"]["page"], 7)
        self.assertFalse(plugin.get_status(view="invalid").success)

    def test_scan_classifies_all_known_entries_even_after_new_job_limit(self):
        plugin = self.rss_setup()
        plugin._valid_config = lambda log_error=False: True
        plugin._reconcile_jobs = lambda jobs: None
        plugin._resume_waiting_jobs = lambda jobs: None
        plugin._refresh_target_jobs = lambda jobs, site: None
        plugin._find_and_download_jobs = lambda jobs: None
        existing = self.rss_job(3, rss_current=True)
        removed = self.rss_job(4, rss_current=True)
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job for job in (existing, removed)}
        created = []

        def create(item, key, site):
            number = int(plugin_module.extract_torrent_id(item["link"]))
            created.append(number)
            return self.rss_job(number)

        plugin._create_job = create
        items = [{
            "title": f"Torrent {number}",
            "enclosure": f"https://target/download?id={number}&passkey=new-secret",
            "link": f"https://target/details.php?id={number}",
        } for number in (1, 2, 3)]
        site = SimpleNamespace(name="target", proxy=False, ua=None)
        with patch.object(plugin_module, "SiteOper", lambda: SimpleNamespace(get=lambda _: site)), \
                patch.object(plugin_module, "RssHelper", lambda: SimpleNamespace(parse=lambda *args, **kwargs: items)):
            plugin.scan()
        jobs = plugin.get_data(plugin.JOBS_KEY)
        self.assertEqual(created, [1])
        self.assertTrue(existing["rss_current"])
        self.assertFalse(removed["rss_current"])
        self.assertEqual(len(jobs), 3)
        snapshots = plugin.get_data(plugin.RSS_SNAPSHOTS_KEY)
        self.assertEqual(snapshots[plugin._rss_source_keys()[0]]["torrent_ids"], ["1", "2", "3"])
        self.assertNotIn("secret", str(snapshots))

    def test_scan_failure_preserves_snapshot_and_successful_empty_rss_archives(self):
        plugin = self.rss_setup()
        plugin._valid_config = lambda log_error=False: True
        plugin._reconcile_jobs = lambda jobs: None
        plugin._resume_waiting_jobs = lambda jobs: None
        job = self.rss_job(1, rss_current=True, state="SOURCE_DOWNLOADING")
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job}
        source_key = plugin._rss_source_keys()[0]
        plugin._data[plugin.RSS_SNAPSHOTS_KEY] = {source_key: self.rss_snapshot([1])}
        site = SimpleNamespace(proxy=False, ua=None)
        with patch.object(plugin_module, "SiteOper", lambda: SimpleNamespace(get=lambda _: site)), \
                patch.object(plugin_module, "RssHelper", lambda: SimpleNamespace(parse=lambda *args, **kwargs: False)):
            plugin.scan()
        self.assertTrue(job["rss_current"])
        self.assertEqual(plugin.get_data(plugin.RSS_SNAPSHOTS_KEY)[source_key]["torrent_ids"], ["1"])
        with patch.object(plugin_module, "SiteOper", lambda: SimpleNamespace(get=lambda _: site)), \
                patch.object(plugin_module, "RssHelper", lambda: SimpleNamespace(parse=lambda *args, **kwargs: [])):
            plugin.scan()
        self.assertFalse(job["rss_current"])
        self.assertEqual(job["state"], "SOURCE_DOWNLOADING")
        self.assertIsNone(plugin.get_data(plugin.RSS_SNAPSHOTS_KEY)[source_key]["error"])

    def test_history_retention_does_not_prune_current_or_downloading_jobs(self):
        plugin = self.rss_setup()
        jobs = [self.rss_job(number, rss_current=False, state="SKIPPED_NO_IYUU_MATCH") for number in range(1, 1002)]
        current = self.rss_job(2000, rss_current=True)
        active = self.rss_job(2001, state="SOURCE_DOWNLOADING", rss_current=False)
        plugin._save_jobs({job["target_hash"]: job for job in [*jobs, current, active]})
        retained = plugin.get_data(plugin.JOBS_KEY)
        self.assertEqual(len(retained), 1002)
        self.assertIn(current["target_hash"], retained)
        self.assertIn(active["target_hash"], retained)

    def test_sidebar_exposes_only_workbench_and_hides_when_disabled(self):
        plugin = self.rss_setup()
        self.assertEqual([item["nav_key"] for item in plugin.get_sidebar_nav()], ["main"])
        self.assertEqual(plugin.get_sidebar_nav()[0]["title"], "稀缺保种")
        plugin._enabled = False
        self.assertEqual(plugin.get_sidebar_nav(), [])

    def test_filters_combine_before_pagination_in_both_views_without_changing_jobs(self):
        plugin = self.rss_setup()
        jobs = [self.rss_job(
            number, rss_current=number <= 100, title="The World from Above 2010 S05 1080p",
            state="AWAITING_SELECTION", target_seeders=number % 3,
            target_download_factor=0 if number % 2 == 0 else 1,
            candidates=[{"site_id": 7, "site_name": "来源七", "promotion": "non_free"}],
        ) for number in range(1, 201)]
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job for job in jobs}
        before = repr(plugin._data)
        for view in ("current", "history"):
            with self.subTest(view=view):
                expected = {job["target_hash"] for job in jobs
                            if job["rss_current"] == (view == "current")
                            and job["target_download_factor"] == 0 and job["target_seeders"] <= 1}
                seen = set()
                filters = dict(state="AWAITING_SELECTION", promotion="free", source_promotion="non_free",
                               source_site_id=7, min_seeders=0, max_seeders=1)
                for page in range(1, (len(expected) + 4) // 5 + 1):
                    data = plugin.get_status(view=view, page=page, page_size=5, **filters).data
                    self.assertEqual(data["summary"]["total"], 200)
                    self.assertEqual(data["view_total"], 100)
                    self.assertEqual(data["view_summary"]["total"], len(expected))
                    self.assertEqual(data["pagination"]["total"], len(expected))
                    seen.update(job["target_hash"] for job in data["jobs"])
                self.assertEqual(seen, expected)
                reset = plugin.get_status(view=view).data
                self.assertEqual(reset["pagination"]["total"], 100)
                self.assertEqual(plugin.get_status(view=view, page=999, **filters).data["pagination"]["page"], 2)
        self.assertEqual(repr(plugin._data), before)

    def test_filters_distinguish_original_promotion_counts_and_cross_site_candidates(self):
        plugin = self.rss_setup()
        jobs = [
            self.rss_job(1, rss_current=True, target_seeders=0, target_download_factor=0,
                         candidates=[{"site_id": 7, "site_name": "来源七", "promotion": "non_free"}]),
            self.rss_job(2, rss_current=True, target_seeders=2, target_download_factor=0.5),
            self.rss_job(3, rss_current=True, target_seeders=None, target_download_factor=None,
                         probes=[{"site_id": 7, "matched": True}]),
            self.rss_job(4, rss_current=False, candidates=[{"site_id": 8, "site_name": "历史来源"}]),
        ]
        plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job for job in jobs}
        cases = [
            ({"promotion": "free"}, [1]),
            ({"promotion": "non_free"}, [2]),
            ({"promotion": "unknown"}, [3]),
            ({"max_seeders": 0}, [1]),
            ({"min_seeders": 0, "max_seeders": 0}, [1]),
            ({"min_seeders": 2, "max_seeders": 2}, [2]),
            ({"source_site_id": 7}, [1]),
            ({"source_site_id": 1}, []),
            ({"state": "TARGET_SEEDING"}, []),
        ]
        for filters, expected in cases:
            with self.subTest(filters=filters):
                data = plugin.get_status(**filters).data
                self.assertEqual({job["target_hash"] for job in data["jobs"]},
                                 {f"{number:040x}" for number in expected})
                self.assertEqual(data["pagination"]["pages"], 1)
                self.assertEqual({site["value"] for site in data["filter_options"]["source_sites"]}, {"7", "8"})
        for filters in ({"min_seeders": -1}, {"max_seeders": -1},
                        {"min_seeders": 2, "max_seeders": 1}, {"promotion": "invalid"},
                        {"source_promotion": "invalid"}):
            self.assertFalse(plugin.get_status(**filters).success)

    def test_cross_site_promotion_and_site_must_match_the_same_candidate_in_both_views(self):
        plugin = self.rss_setup()
        for view in ("current", "history"):
            with self.subTest(view=view):
                jobs = [
                    self.rss_job(1, candidates=[{"site_id": 7, "promotion": "non_free"},
                                                {"site_id": 8, "promotion": "free"}]),
                    self.rss_job(2, candidates=[{"site_id": 7, "promotion": "free"}]),
                    self.rss_job(3, candidates=[{"site_id": 7, "promotion": "unknown"}]),
                    self.rss_job(4, candidates=[], probes=[{"site_id": 7, "promotion": "free"}]),
                    self.rss_job(5, candidates=[{"site_id": 7, "download_factor": 0.5}]),
                    self.rss_job(6, candidates=[{"site_id": 7, "download_factor": 0}]),
                    self.rss_job(7, candidates=[{"site_id": 7, "download_factor": None}]),
                ]
                for job in jobs:
                    job.update(rss_current=view == "current", target_download_factor=1)
                plugin._data[plugin.JOBS_KEY] = {job["target_hash"]: job for job in jobs}
                cases = [
                    ({"source_promotion": "free"}, [1, 2, 6]),
                    ({"source_promotion": "non_free"}, [1, 5]),
                    ({"source_promotion": "unknown"}, [3, 7]),
                    ({"source_site_id": 7, "source_promotion": "free"}, [2, 6]),
                    ({"source_site_id": 8, "source_promotion": "non_free"}, []),
                    ({"promotion": "non_free", "source_promotion": "free"}, [1, 2, 6]),
                    ({"promotion": "free", "source_promotion": "free"}, []),
                    ({"source_site_id": 1, "source_promotion": "non_free"}, []),
                ]
                for filters, expected in cases:
                    with self.subTest(filters=filters):
                        data = plugin.get_status(view=view, **filters).data
                        self.assertEqual({job["target_hash"] for job in data["jobs"]},
                                         {f"{number:040x}" for number in expected})
                        self.assertEqual(data["view_total"], 7)
                self.assertEqual(plugin.get_status(view=view).data["pagination"]["total"], 7)


if __name__ == "__main__":
    unittest.main()

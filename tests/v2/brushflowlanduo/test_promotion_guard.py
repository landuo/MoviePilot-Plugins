import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


GUARD_PATH = Path(__file__).parents[3] / "plugins.v2/brushflowlanduo/promotion_guard.py"
spec = importlib.util.spec_from_file_location("promotion_guard", GUARD_PATH)
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

TASK = {"id": "dcfeede5f1b2450d839fdea33791d9f2", "site_id": 11,
        "downloader": "qb", "del_no_free": True, "freeleech": "free", "download_time": 4}


def torrent(**overrides):
    data = {"hash": "a" * 40, "progress": 0.3, "amount_left": 700,
            "downloaded": 5000, "total_size": 1000, "state": "downloading",
            "tags": "已整理, 刷流, 刷流-dcfeede5", "added_on": time.time() - 3600}
    data.update(overrides)
    return data


def record(now, **overrides):
    data = {"task_id": TASK["id"], "site": 11, "downloadvolumefactor": 0,
            "promotion_verified_at": now, "promotion_probe_at": now,
            "promotion_clock_version": 2,
            "freedate": datetime.fromtimestamp(now + 7200, timezone.utc).isoformat()}
    data.update(overrides)
    return data


class GuardPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = int(time.time())

    def reason(self, row=None, item=None, now=None):
        return guard.pause_reason(TASK, item or torrent(), row or record(self.now), now or self.now)

    def test_fresh_verified_download_keeps_running(self):
        self.assertIsNone(self.reason())

    def test_real_deadline_is_ten_minutes_early(self):
        row = record(self.now, freedate=datetime.fromtimestamp(self.now + 600, timezone.utc).isoformat())
        self.assertEqual(self.reason(row), "promotion_deadline")

    def test_stopped_hung_and_restarting_moviepilot_cannot_renew_lease(self):
        row = record(self.now)
        for interruption in (1020, 3600, 12 * 3600):
            with self.subTest(seconds_without_moviepilot=interruption):
                self.assertEqual(self.reason(row, now=self.now + interruption), "verification_lease_expired")

    def test_download_time_limit_does_not_need_moviepilot(self):
        self.assertEqual(self.reason(item=torrent(added_on=self.now - 4 * 3600)), "download_time_limit")

    def test_old_shifted_deadline_requires_new_verification(self):
        row = record(self.now)
        row.pop("promotion_clock_version")
        self.assertEqual(self.reason(row), "legacy_unverified_clock")

    def test_declared_deadline_is_absolute(self):
        dt = datetime.fromtimestamp(self.now + 600, timezone.utc)
        row = record(self.now, freedate=dt.isoformat())
        self.assertEqual(self.reason(row), "promotion_deadline")
        self.assertEqual(self.reason(record(self.now, freedate="2099-01-01 00:00:00")),
                         "deadline_without_timezone")

    def test_failed_probe_future_clock_and_missing_deadline_pause(self):
        for changes, expected in (({"promotion_probe_at": self.now + 1}, "last_verification_failed"),
                                  ({"promotion_verified_at": self.now + 3600}, "verification_missing_or_future"),
                                  ({"freedate": None}, "deadline_missing"),
                                  ({"promotion_ended_at": self.now}, "promotion_ended")):
            with self.subTest(changes=changes):
                self.assertEqual(self.reason(record(self.now, **changes)), expected)

    def test_completed_unmanaged_other_site_and_other_task_are_untouched(self):
        old = record(self.now - 10000)
        for item in (torrent(progress=1, amount_left=0, state="stalledUP"),
                     torrent(progress=0.5, amount_left=0, state="checkingUP"),
                     torrent(tags="刷流, 正常下载"), torrent(tags="刷流-aa94b5e9")):
            with self.subTest(item=item):
                self.assertIsNone(self.reason(old, item=item))
        for changes in ({"task_id": "other"}, {"site": 18}, {"deleted": True}):
            self.assertIsNone(self.reason(record(self.now - 10000, **changes)))

    def test_new_tagged_torrent_without_saved_record_cannot_download(self):
        self.assertEqual(guard.pause_reason(TASK, torrent(), None, self.now), "missing_managed_record")


class FakeQbHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if self.headers.get("Cookie") != "SID=test":
            self.send_error(403)
            return
        self.server.reads += 1
        if self.server.pending_stop:
            if self.server.confirm_delay > 0:
                self.server.confirm_delay -= 1
            else:
                for item in self.server.items:
                    if item["hash"] in self.server.pending_stop:
                        item["state"] = "stoppedDL"
        if self.server.finish_on_recheck and self.server.reads == 2:
            self.server.items[0].update(progress=1, amount_left=0, state="stalledUP")
        rows = self.server.items
        if "tag" in params:
            rows = [x for x in rows if params["tag"][0] in x["tags"]]
        if "hashes" in params:
            rows = [x for x in rows if x["hash"] in params["hashes"][0].split("|")]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(rows).encode())

    def do_POST(self):
        form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        if self.path.endswith("/auth/login"):
            self.send_response(200)
            self.send_header("Set-Cookie", "SID=test; Path=/")
            self.end_headers()
            self.wfile.write(b"Ok.")
            return
        if self.server.old_api and self.path.endswith("/torrents/stop"):
            self.send_error(404)
            return
        assert self.path.endswith(("/torrents/stop", "/torrents/pause"))
        hashes = form["hashes"][0].split("|")
        self.server.stops.extend(hashes)
        if self.server.confirm_delay:
            self.server.pending_stop = hashes
        for item in self.server.items:
            if item["hash"] in hashes and not self.server.ignore_stop and not self.server.confirm_delay:
                item["state"] = "stoppedDL"
        self.send_response(200)
        self.end_headers()


class IndependentGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeQbHandler)
        self.server.items = [torrent(), torrent(hash="b" * 40, state="stalledUP", progress=1, amount_left=0),
                             torrent(hash="c" * 40, tags="刷流, 刷流-aa94b5e9")]
        self.server.stops = []
        self.server.reads = 0
        self.server.finish_on_recheck = False
        self.server.old_api = False
        self.server.ignore_stop = False
        self.server.confirm_delay = 0
        self.server.pending_stop = []
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.database = Path(self.temp.name) / "user.db"
        self.db = sqlite3.connect(self.database)
        self.addCleanup(self.db.close)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE systemconfig(key TEXT,value JSON)")
        self.db.execute("CREATE TABLE plugindata(plugin_id TEXT,key TEXT,value JSON)")
        downloader = {"name": "qb", "type": "qbittorrent", "config": {
            "host": f"http://127.0.0.1:{self.server.server_port}/", "username": "user", "password": "never-print-secret"}}
        self.db.execute("INSERT INTO systemconfig VALUES(?,?)", ("Downloaders", json.dumps([downloader])))
        self.db.execute("INSERT INTO systemconfig VALUES(?,?)", (
            "plugin.BrushFlowLanduo", json.dumps({"enabled": False, "tasks": [TASK, dict(TASK, id="other")]})))
        self.rows = {x["hash"]: record(time.time() - 2000) for x in self.server.items}
        self.db.execute("INSERT INTO plugindata VALUES(?,?,?)", (
            "BrushFlowLanduo", f"task.{TASK['id']}.torrents", json.dumps(self.rows)))
        self.db.commit()
        self.loader = lambda: guard.read_snapshot(self.database, {TASK["id"]})

    def test_separate_python_process_stops_only_expired_managed_download(self):
        # No MoviePilot modules/process or scheduler exist in this independent process.
        process = subprocess.run([sys.executable, str(GUARD_PATH), "--once", "--database", str(self.database),
                                  "--task-id", TASK["id"], "--status-file", str(Path(self.temp.name) / "status.json")],
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(self.server.stops, ["a" * 40])
        self.assertNotIn("never-print-secret", process.stdout + process.stderr)
        self.assertEqual(json.loads(process.stdout)["paused"], 1)
        self.assertEqual(self.db.total_changes, 3, "guard must never write to the application DB")

    def test_wal_snapshot_is_scoped_and_dry_run_cannot_pause(self):
        self.assertEqual(len(self.loader()), 1)
        result = guard.Guard(self.loader).run_once(dry_run=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["would_pause"], 1)
        self.assertEqual(self.server.stops, [])

    def test_cold_guard_reads_checkpointed_db_after_moviepilot_stops(self):
        self.db.close()
        self.assertFalse(Path(str(self.database) + "-wal").exists())
        self.database.chmod(0o400)
        Path(self.temp.name).chmod(0o500)
        try:
            snapshot = self.loader()
            self.assertEqual(len(snapshot), 1)
            self.assertEqual(snapshot[0][0]["id"], TASK["id"])
            self.assertEqual(list(Path(self.temp.name).iterdir()), [self.database])
            self.assertEqual(guard.Guard(self.loader).run_once()["paused"], 1)
        finally:
            Path(self.temp.name).chmod(0o700)

    def test_torrent_finishing_before_stop_is_not_paused(self):
        self.server.finish_on_recheck = True
        guard.Guard(self.loader).run_once()
        self.assertEqual(self.server.stops, [])

    def test_pause_endpoint_falls_back_for_qb_v4(self):
        self.server.old_api = True
        result = guard.Guard(self.loader).run_once()
        self.assertTrue(result["ok"])
        self.assertEqual(self.server.stops, ["a" * 40])

    def test_qb_accepting_but_ignoring_stop_is_unhealthy(self):
        self.server.ignore_stop = True
        self.assertFalse(guard.Guard(self.loader).run_once()["ok"])

    def test_async_qb_state_confirmation_is_retried(self):
        self.server.confirm_delay = 1
        self.assertTrue(guard.Guard(self.loader).run_once()["ok"])
        self.assertEqual(self.server.stops, ["a" * 40])

    def test_read_failure_uses_last_scope_to_stop_unsafe_download(self):
        self.rows["a" * 40] = record(time.time())
        self.db.execute("UPDATE plugindata SET value=?", (json.dumps(self.rows),))
        self.db.commit()
        service = guard.Guard(self.loader)
        self.assertEqual(service.run_once()["paused"], 0)
        service.loader = lambda: (_ for _ in ()).throw(sqlite3.OperationalError("locked"))
        result = service.run_once()
        self.assertFalse(result["ok"])
        self.assertEqual(self.server.stops, ["a" * 40])


if __name__ == "__main__":
    unittest.main()

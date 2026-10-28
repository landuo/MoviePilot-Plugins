"""Independent qBittorrent promotion guard. Run outside the MoviePilot container.

Reads MoviePilot's SQLite database read-only; never queries a tracker, resumes a
torrent, deletes files, or writes to MoviePilot's database. Credentials stay in
memory and are read from the existing downloader configuration.
"""

import argparse
import http.cookiejar
import json
import logging
import math
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener


CLOCK_VERSION = 2
VERIFY_INTERVAL = 15 * 60
SCHEDULER_GRACE = 2 * 60
STOP_MARGIN = 10 * 60
POLL_INTERVAL = 15
LOG = logging.getLogger("brushflow-promotion-guard")


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else 0
    except (ValueError, TypeError):
        return 0


def read_snapshot(database, task_ids):
    """Read config and records in one consistent SQLite transaction, including WAL."""
    database = Path(database).resolve()
    wal = Path(str(database) + "-wal")
    checkpointed = not wal.exists()
    # A clean MoviePilot shutdown removes WAL/SHM. SQLite otherwise tries to
    # create them even for mode=ro, which is impossible on the read-only mount.
    # Only the checkpointed main DB may use immutable; never ignore a live WAL.
    uri = f"{database.as_uri()}?mode=ro" + ("&immutable=1" if checkpointed else "")
    with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        config_row = db.execute("SELECT value FROM systemconfig WHERE key=?",
                                ("plugin.BrushFlowLanduo",)).fetchone()
        if not config_row:
            raise ValueError("missing_plugin_configuration")
        config = json.loads(config_row[0])
        row = db.execute("SELECT value FROM systemconfig WHERE key=?", ("Downloaders",)).fetchone()
        downloaders = {d["name"]: d for d in json.loads(row[0])} if row else {}
        snapshot = []
        for task in config.get("tasks", []):
            if task.get("id") not in task_ids or not task.get("del_no_free"):
                continue
            if task.get("freeleech", "free") not in {"free", "2xfree"}:
                continue
            downloader = downloaders.get(task.get("downloader"))
            if not downloader or downloader.get("type") != "qbittorrent":
                raise ValueError("guard_requires_qbittorrent")
            row = db.execute('SELECT value FROM plugindata WHERE plugin_id=? AND "key"=?',
                             ("BrushFlowLanduo", f"task.{task['id']}.torrents")).fetchone()
            records = json.loads(row[0]) if row else {}
            snapshot.append((task, records, downloader))
        if checkpointed and wal.exists():
            raise sqlite3.OperationalError("WAL appeared during checkpointed snapshot")
        return snapshot


def complete(torrent):
    # Cumulative transfer bytes can exceed file size while files remain incomplete.
    state = str(torrent.get("state", "")).lower()
    return (state in {"uploading", "stalledup", "forcedup", "pausedup", "stoppedup", "queuedup", "checkingup"}
            or (number(torrent.get("progress")) >= 1 and number(torrent.get("amount_left")) <= 0))


def pause_reason(task, torrent, record, now):
    """Return a reason only for this task's tagged, unfinished, managed downloads."""
    tag = f"刷流-{task['id'][:8]}"
    if tag not in {x.strip() for x in str(torrent.get("tags", "")).split(",")} or complete(torrent):
        return None
    if record and (record.get("deleted") or record.get("task_id") != task["id"]
                   or record.get("site") != task.get("site_id")):
        return None
    # A crash between adding and saving must not leave an untracked download running.
    if not record:
        return "missing_managed_record"
    if record.get("promotion_clock_version") != CLOCK_VERSION:
        return "legacy_unverified_clock"
    if record.get("promotion_ended_at"):
        return "promotion_ended"
    factor = record.get("downloadvolumefactor")
    try:
        free = float(factor) == 0 if factor is not None else record.get("volume_factor") in {"免费", "2X免费", "4X免费"}
    except (ValueError, TypeError):
        free = False
    if not free:
        return "free_status_unverified"
    verified = number(record.get("promotion_verified_at"))
    if not verified or verified > now + 30:
        return "verification_missing_or_future"
    if now >= verified + VERIFY_INTERVAL + SCHEDULER_GRACE:
        return "verification_lease_expired"
    if number(record.get("promotion_probe_at")) > verified:
        return "last_verification_failed"
    try:
        deadline = datetime.fromisoformat(str(record.get("freedate")))
        if deadline.tzinfo is None:
            return "deadline_without_timezone"
        expiry = deadline.timestamp()
    except (ValueError, TypeError, OverflowError):
        return "deadline_missing"
    if now >= expiry - STOP_MARGIN:
        return "promotion_deadline"
    limit = number(task.get("download_time")) * 3600
    added = number(torrent.get("added_on"))
    if limit > 0 and added > 0 and now >= added + limit:
        return "download_time_limit"
    return None


class QbClient:
    def __init__(self, config):
        self.config = config
        self.base = str(config["host"]).rstrip("/") + "/"
        parsed = urlparse(self.base)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
            raise ValueError("invalid_downloader_url")
        self.opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.logged_in = False

    def request(self, endpoint, data=None, *, authenticate=True):
        if authenticate and not self.logged_in:
            reply = self.request("auth/login", {"username": self.config.get("username", ""),
                                                "password": self.config.get("password", "")}, authenticate=False)
            if reply.strip() != b"Ok.":
                raise RuntimeError("qb_login_failed")
            self.logged_in = True
        body = urlencode(data).encode() if data is not None else None
        request = Request(self.base + "api/v2/" + endpoint, data=body,
                          headers={"Referer": self.base})
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.read()
        except HTTPError as err:
            if err.code == 403 and authenticate:
                self.logged_in = False
            err.close()
            raise

    def torrents(self, **query):
        result = json.loads(self.request("torrents/info?" + urlencode(query)))
        if not isinstance(result, list):
            raise ValueError("invalid_torrent_response")
        return result

    def stop(self, hashes):
        try:
            self.request("torrents/stop", {"hashes": "|".join(hashes)})
        except HTTPError as err:
            if err.code != 404:
                raise
            self.request("torrents/pause", {"hashes": "|".join(hashes)})


class Guard:
    def __init__(self, loader, client_factory=QbClient):
        self.loader = loader
        self.client_factory = client_factory
        self.snapshot = None
        self.clients = {}

    def run_once(self, *, dry_run=False, now=None):
        now = time.time() if now is None else now
        read_failed = False
        try:
            self.snapshot = self.loader()
        except Exception as err:
            # Do not log exception messages: URLs or DB contents may contain secrets.
            LOG.error("database_read_failed type=%s", type(err).__name__)
            if self.snapshot is None:
                raise RuntimeError("no_known_guard_scope") from None
            read_failed = True
        result = {"ok": not read_failed, "guarded": 0, "would_pause": 0, "paused": 0}
        for task, records, downloader in self.snapshot:
            try:
                name, config = downloader["name"], downloader["config"]
                if name not in self.clients or self.clients[name].config != config:
                    self.clients[name] = self.client_factory(config)
                client = self.clients[name]
                torrents = client.torrents(tag=f"刷流-{task['id'][:8]}")
                result["guarded"] += len(torrents)

                def reason(torrent):
                    record = records.get(torrent.get("hash"))
                    value = pause_reason(task, torrent, record, now)
                    if value is None and read_failed and not complete(torrent):
                        # Same ownership checks still apply when using the cached scope.
                        check = dict(record or {}, promotion_verified_at=0)
                        value = pause_reason(task, torrent, check, now)
                    return value

                candidates = {t["hash"] for t in torrents if reason(t)
                              and str(t.get("state", "")).lower() not in {"stoppeddl", "pauseddl"}}
                if not candidates:
                    continue
                # Re-read actual completion/tags immediately before pausing; a download may have finished.
                latest = client.torrents(hashes="|".join(sorted(candidates)))
                decisions = {t["hash"]: reason(t) for t in latest if t.get("hash") in candidates and reason(t)}
                result["would_pause"] += len(decisions)
                if dry_run or not decisions:
                    continue
                client.stop(list(decisions))
                # qB's stop RPC returns before its torrent-info cache necessarily changes.
                for attempt in range(5):
                    after = client.torrents(hashes="|".join(decisions))
                    pending = [t for t in after if not complete(t)
                               and str(t.get("state", "")).lower() not in {"stoppeddl", "pauseddl"}]
                    if not pending or attempt == 4:
                        break
                    time.sleep(0.25)
                for torrent in after:
                    torrent_hash = torrent.get("hash")
                    if torrent_hash not in decisions:
                        continue
                    if complete(torrent) or str(torrent.get("state", "")).lower() in {"stoppeddl", "pauseddl"}:
                        result["paused"] += 1
                        LOG.warning("paused task=%s hash=%s reason=%s", task["id"], torrent_hash,
                                    decisions[torrent_hash])
                    else:
                        result["ok"] = False
                        LOG.error("pause_not_confirmed task=%s hash=%s", task["id"], torrent_hash)
            except Exception as err:
                result["ok"] = False
                LOG.error("downloader_guard_failed task=%s type=%s", task["id"], type(err).__name__)
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", default="/config/user.db")
    parser.add_argument("--task-id", action="append", default=[])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-file", default="/tmp/brushflow-guard-status.json")
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        try:
            status = json.loads(Path(args.status_file).read_text())
            return 0 if status.get("ok") and 0 <= time.time() - status["at"] < 120 else 1
        except (OSError, ValueError, KeyError):
            return 1
    if not args.task_id:
        parser.error("at least one --task-id is required")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    guard = Guard(lambda: read_snapshot(args.database, set(args.task_id)))
    while True:
        try:
            status = guard.run_once(dry_run=args.dry_run)
        except Exception as err:
            LOG.error("guard_failed type=%s", type(err).__name__)
            status = {"ok": False}
        status["at"] = time.time()
        Path(args.status_file).write_text(json.dumps(status))
        if args.once or args.dry_run:
            print(json.dumps(status))
            return 0 if status["ok"] else 1
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())

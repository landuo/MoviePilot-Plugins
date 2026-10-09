"""MoviePilot V2 稀缺保种插件。"""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app import schemas
from app.chain.download import DownloadChain
from app.chain.torrents import TorrentsChain
from app.core.config import settings
from app.core.plugin import PluginManager
from app.db.site_oper import SiteOper
from app.helper.downloader import DownloaderHelper
from app.helper.rss import RssHelper
from app.helper.sites import SitesHelper
from app.helper.torrent import TorrentHelper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.utils.string import StringUtils
from app.utils.http import RequestUtils

from .core import (
    FREE,
    NON_FREE,
    UNKNOWN,
    IyuuMatch,
    SourceCandidate,
    extract_torrent_id,
    feed_key,
    info_hash_from_torrent,
    iyuu_matches_for_hash,
    normalize_promotions,
    promotion_kind,
    ranked_sources,
    safe_page_url,
    search_keywords,
    torrent_is_complete,
    target_torrent_status,
)
from .models import CandidateSelectionPayload
from .detail import DetailResult, detail_url, fetch_detail

try:
    from app.plugins.iyuuautoseed.iyuu_helper import IyuuHelper
except ImportError:  # pragma: no cover - 仅在宿主缺少 IYUU 插件时出现
    IyuuHelper = None


class ScanInterrupted(Exception):
    """插件停止时在安全检查点结束扫描。"""


class DownloadSubmissionUncertain(Exception):
    """添加请求结果未知，禁止换来源或重复提交。"""


class SeedRescue(_PluginBase):
    """从高保种来源下载 RSS 目标的同源数据，再交给 IYUU 辅种。"""

    plugin_name = "稀缺保种"
    plugin_desc = "读取目标站RSS，可选择跨站同源候选下载后辅种，也可直接下载保种站点原种。"
    plugin_icon = "IYUU.png"
    plugin_version = "1.6.3"
    plugin_author = "landuo"
    author_url = "https://github.com/landuo"
    plugin_config_prefix = "seedrescue_"
    plugin_order = 18
    auth_level = 2

    JOBS_KEY = "jobs"
    RSS_SNAPSHOTS_KEY = "rss_snapshots"
    SCAN_STATUS_KEY = "scan_status"
    MAX_AUTO_RETRIES = 5
    MAX_SOURCE_PAGES = 3
    MAX_SOURCE_SEARCHES = 8
    TARGET_REFRESH_INTERVAL = timedelta(minutes=30)
    TARGET_RETRY_INTERVAL = timedelta(hours=1)
    CATEGORY = "seed-rescue"
    GLOBAL_TAG = "seed-rescue"
    _selection_mode = "manual"
    ACTIVE_STATES = {
        "SOURCE_SUBMITTING",
        "TARGET_SEEDING",
        "TARGET_COMPLETE",
        "TARGET_PAUSED",
        "TARGET_ERROR",
        "SOURCE_DOWNLOADING",
        "TARGET_DOWNLOADING",
        "WAITING_IYUU",
        "WAITING_IYUU_RETRY",
        "TARGET_RECHECKING",
        "AWAITING_SELECTION",
    }
    DOWNLOAD_STARTED_STATES = {
        "SOURCE_SUBMITTING",
        "TARGET_COMPLETE",
        "TARGET_PAUSED",
        "TARGET_ERROR",
        "SOURCE_DOWNLOADING",
        "TARGET_DOWNLOADING",
        "WAITING_IYUU",
        "TARGET_RECHECKING",
        "TARGET_SEEDING",
    }
    TARGET_SELECTABLE_STATES = {
        "WAITING_SOURCE_RETRY",
        "FAILED_MATCHING",
        "AWAITING_SELECTION",
        "WAITING_CAPACITY",
        "WAITING_IYUU_RETRY",
        "SKIPPED_NO_IYUU_MATCH",
        "SKIPPED_NO_HEALTHY_SOURCE",
        "FAILED_TARGET_TORRENT",
        "FAILED_SOURCE_DOWNLOAD",
    }
    TERMINAL_STATES = {
        "FAILED_MATCHING",
        "TARGET_SEEDING",
        "SKIPPED_NO_IYUU_MATCH",
        "SKIPPED_NO_HEALTHY_SOURCE",
        "FAILED_TARGET_TORRENT",
        "FAILED_SOURCE_DOWNLOAD",
    }

    def init_plugin(self, config: dict = None) -> None:
        """读取配置；定时任务由 MoviePilot 公共服务调度。"""

        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._notify = bool(config.get("notify", True))
        self._confirm_download_risk = config.get("confirm_download_risk") is not False
        self._run_once = bool(config.get("onlyonce", False))
        self._onlyonce = False
        self._cron = str(config.get("cron") or "*/30 * * * *").strip()
        self._token = str(config.get("token") or "").strip()
        self._target_site_id = self._positive_int(config.get("target_site_id"), 0)
        self._rss_urls = self._lines(config.get("rss_urls"))
        self._source_site_ids = list(dict.fromkeys(
            self._positive_int(value, 0)
            for value in config.get("source_site_ids") or []
            if self._positive_int(value, 0) not in {0, self._target_site_id}
        ))
        self._minimum_seeders = self._optional_limit(config.get("minimum_seeders"), 1)
        promotion_config = config.get("allowed_promotions")
        self._allowed_promotions = normalize_promotions(
            [FREE, NON_FREE] if promotion_config is None else promotion_config
        )
        self._downloader_name = str(config.get("downloader") or "").strip()
        self._save_path = str(config.get("save_path") or "").strip() or None
        self._max_download_count = self._optional_limit(config.get("max_download_count"), 2)
        self._initial_limit = self._optional_limit(config.get("initial_limit"), 20)
        selection_mode = str(config.get("selection_mode") or "manual").strip().lower()
        self._selection_mode = (
            selection_mode if selection_mode in {"manual", "auto", "hybrid"} else "manual"
        )
        if not hasattr(self, "_lock"):
            self._lock = threading.Lock()
        if not hasattr(self, "_site_search_locks"):
            self._site_search_locks: Dict[str, threading.Lock] = {}
            self._site_search_locks_guard = threading.Lock()
        if not hasattr(self, "_source_probe_slots"):
            self._source_probe_slots = threading.BoundedSemaphore(6)
        self._ensure_scan_runtime()
        self._iyuu = IyuuHelper(self._token) if IyuuHelper and self._token else None
        if self._run_once:
            self._save_config()

    @staticmethod
    def _lines(value: Any) -> List[str]:
        if isinstance(value, list):
            rows = value
        else:
            rows = str(value or "").splitlines()
        return list(dict.fromkeys(str(row).strip() for row in rows if str(row).strip()))

    @staticmethod
    def _positive_int(value: Any, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    @staticmethod
    def _optional_limit(value: Any, default: int) -> Optional[int]:
        """未设置、留空或 0 表示无限制；非法值沿用原来的安全默认值。"""

        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            parsed = int(value)
            if isinstance(value, bool) or parsed < 0 or float(value) != parsed:
                return default
        except (TypeError, ValueError, OverflowError):
            return default
        return parsed or None

    def _current_config(self) -> dict:
        return {
            "enabled": self._enabled,
            "notify": self._notify,
            "confirm_download_risk": self._confirm_download_risk,
            "onlyonce": self._onlyonce,
            "cron": self._cron,
            "token": self._token,
            "target_site_id": self._target_site_id,
            "rss_urls": "\n".join(self._rss_urls),
            "source_site_ids": self._source_site_ids,
            "minimum_seeders": self._minimum_seeders,
            "allowed_promotions": sorted(self._allowed_promotions),
            "downloader": self._downloader_name,
            "save_path": self._save_path or "",
            "max_download_count": self._max_download_count,
            "initial_limit": self._initial_limit,
            "selection_mode": self._selection_mode,
        }

    def _save_config(self) -> None:
        self.update_config(self._current_config())

    def get_state(self) -> bool:
        """返回插件是否启用。"""

        return bool(self._enabled)

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """返回插件远程命令列表。"""

        return []

    @staticmethod
    def get_render_mode() -> Tuple[str, str]:
        """声明使用 Vue 联邦组件渲染插件界面。"""

        return "vue", "dist/assets"

    def get_sidebar_nav(self) -> List[Dict[str, Any]]:
        """返回稀缺保种工作台的侧栏入口。"""

        if not self.get_state():
            return []
        return [{
            "nav_key": "main",
            "title": "稀缺保种",
            "icon": "mdi-seed-outline",
            "section": "organize",
            "permission": "manage",
            "order": 46,
        }]

    def get_api(self) -> List[Dict[str, Any]]:
        """返回工作台使用的 Bearer 认证接口。"""

        return [
            {
                "path": "/status",
                "endpoint": self.get_status,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取稀缺保种状态",
            },
            {
                "path": "/scan",
                "endpoint": self.scan_now,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即扫描目标站 RSS",
            },
            {
                "path": "/jobs/{target_hash}",
                "endpoint": self.get_job,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取保种任务详情",
            },
            {
                "path": "/jobs/{target_hash}/download",
                "endpoint": self.download_candidate,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "下载用户选择的来源种子",
            },
            {
                "path": "/jobs/{target_hash}/retry",
                "endpoint": self.retry_job,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "重新匹配保种任务",
            },
            {
                "path": "/jobs/{target_hash}/ignore",
                "endpoint": self.ignore_job,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "忽略保种任务",
            },
        ]

    def get_status(self, view: str = "current", page: int = 1, page_size: int = 20,
                   state: str = "", promotion: str = "", source_promotion: str = "",
                   source_site_id: Optional[int] = None, min_seeders: Optional[int] = None,
                   max_seeders: Optional[int] = None) -> schemas.Response:
        """当前与历史任务共用筛选条件，先筛选全部记录再分页。"""

        if view not in {"current", "history"}:
            return schemas.Response(success=False, message="无效的 RSS 列表类型")
        if promotion and promotion not in {FREE, NON_FREE, UNKNOWN}:
            return schemas.Response(success=False, message="无效的原站促销条件")
        if source_promotion and source_promotion not in {FREE, NON_FREE, UNKNOWN}:
            return schemas.Response(success=False, message="无效的跨站促销条件")
        if any(value is not None and value < 0 for value in (min_seeders, max_seeders)):
            return schemas.Response(success=False, message="做种人数不能为负数")
        if min_seeders is not None and max_seeders is not None and min_seeders > max_seeders:
            return schemas.Response(success=False, message="最低做种人数不能大于最高做种人数")
        jobs = self.get_data(self.JOBS_KEY) or {}
        current_count = sum(job.get("rss_current") is True for job in jobs.values())
        filtered = [
            job for job in jobs.values()
            if (job.get("rss_current") is True) == (view == "current")
        ]
        view_total = len(filtered)
        if state:
            filtered = [job for job in filtered if job.get("state") == state]
        if promotion:
            filtered = [job for job in filtered
                        if promotion_kind(job.get("target_download_factor")) == promotion]
        if source_site_id is not None or source_promotion:
            filtered = [job for job in filtered if any(
                (source_site_id is None or str(candidate.get("site_id")) == str(source_site_id))
                and (not source_promotion or (
                    candidate.get("promotion") or promotion_kind(candidate.get("download_factor"))
                ) == source_promotion)
                for candidate in self._display_candidates(job)
            )]
        if min_seeders is not None or max_seeders is not None:
            filtered = [job for job in filtered if job.get("target_seeders") is not None
                        and (min_seeders is None or job["target_seeders"] >= min_seeders)
                        and (max_seeders is None or job["target_seeders"] <= max_seeders)]
        ordered = sorted(
            filtered,
            key=lambda item: (
                (item.get("rss_last_seen_at") if view == "current" else item.get("rss_archived_at")) or "",
                item.get("created_at") or "",
                item["target_hash"],
            ),
            reverse=True,
        )
        page_size = min(self._positive_int(page_size, 20), 100)
        total_pages = max(1, (len(ordered) + page_size - 1) // page_size)
        page = min(self._positive_int(page, 1), total_pages)
        start = (page - 1) * page_size
        snapshots = self.get_data(self.RSS_SNAPSHOTS_KEY) or {}
        active_snapshots = [snapshots.get(key, {}) for key in self._rss_source_keys()]
        candidate_sites = {
            str(candidate["site_id"]): candidate.get("site_name") or str(candidate["site_id"])
            for job in jobs.values() for candidate in self._display_candidates(job)
            if candidate.get("site_id") is not None
        }
        return schemas.Response(success=True, data={
            "enabled": self._enabled,
            "selection_mode": self._selection_mode,
            "confirm_download_risk": self._confirm_download_risk,
            "scan_status": self._get_scan_status(),
            "busy": self._lock.locked(),
            "summary": {
                **self._job_summary(list(jobs.values())),
                "current": current_count,
                "history": len(jobs) - current_count,
                "unclassified": sum("rss_current" not in job for job in jobs.values()),
            },
            "view": view,
            "view_total": view_total,
            "view_summary": self._job_summary(filtered),
            "filter_options": {"source_sites": [
                {"title": title, "value": site_id}
                for site_id, title in sorted(candidate_sites.items(), key=lambda item: item[1])
            ]},
            "pagination": {"page": page, "page_size": page_size, "total": len(ordered), "pages": total_pages},
            "rss_status": {
                "configured_feeds": len(active_snapshots),
                "failed_feeds": sum(bool(snapshot.get("error")) for snapshot in active_snapshots),
                "last_attempt_at": max((snapshot.get("last_attempt_at") or "" for snapshot in active_snapshots), default=""),
                "last_success_at": max((snapshot.get("last_success_at") or "" for snapshot in active_snapshots), default=""),
            },
            "jobs": [self._job_view(job) for job in ordered[start:start + page_size]],
            "options": self._frontend_options(),
        })

    @staticmethod
    def _job_summary(jobs: List[dict]) -> dict:
        counts = Counter(job.get("state") for job in jobs)
        return {
            "total": len(jobs),
            "awaiting_selection": counts.get("AWAITING_SELECTION", 0),
            "downloading": counts.get("SOURCE_DOWNLOADING", 0) + counts.get("TARGET_DOWNLOADING", 0),
            "waiting_iyuu": counts.get("WAITING_IYUU", 0),
            "target_seeding": counts.get("TARGET_SEEDING", 0),
            "failed": sum(count for state, count in counts.items() if str(state).startswith("FAILED")),
        }

    def scan_now(self) -> schemas.Response:
        """先原子占用执行名额，再提交后台扫描，接口不等待网络任务。"""

        if not self._valid_config(log_error=False):
            return schemas.Response(success=False, message="插件配置不完整或下载器不可用")
        if not self._lock.acquire(blocking=False):
            return schemas.Response(success=False, message="稀缺保种任务正在运行")
        try:
            self._begin_scan()
            self._scan_thread = threading.Thread(target=self._run_scan, name="seedrescue-scan", daemon=True)
            self._scan_thread.start()
        except Exception:
            self._lock.release()
            self._scan_update(state="failed", message="后台扫描启动失败", finished_at=self._now())
            return schemas.Response(success=False, message="后台扫描启动失败")
        return schemas.Response(success=True, message="已提交后台扫描", data={"scan_status": self._get_scan_status()})

    def _ensure_scan_runtime(self) -> None:
        if hasattr(self, "_scan_status_lock"):
            return
        self._scan_status_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._scan_thread = None
        self._scan_jobs = None
        self._scan_status = dict(self.get_data(self.SCAN_STATUS_KEY) or {"state": "idle"})
        if self._scan_status.get("state") == "running":
            self._scan_update(state="interrupted", finished_at=self._now(),
                              message="上次扫描被中断，未完成的匹配将在下次扫描恢复")

    def _get_scan_status(self) -> dict:
        self._ensure_scan_runtime()
        with self._scan_status_lock:
            return dict(self._scan_status)

    def _scan_update(self, **fields: Any) -> None:
        with self._scan_status_lock:
            if self._stop_event.is_set():
                return
            self._scan_status = {**self._scan_status, **fields}
            self.save_data(self.SCAN_STATUS_KEY, dict(self._scan_status))

    def _begin_scan(self) -> None:
        self._ensure_scan_runtime()
        self._stop_event.clear()
        self._scan_status = {}
        self._scan_update(state="running", stage="preparing", completed=0, total=0,
                          started_at=self._now(), finished_at=None, errors=0, issues=[], message="正在准备扫描")

    def _scan_stage(self, stage: str, total: int = 0) -> None:
        if getattr(self, "_scan_jobs", None) is not None:
            self._scan_update(stage=stage, completed=0, total=total)

    def _scan_advance(self) -> None:
        if getattr(self, "_scan_jobs", None) is not None:
            with self._scan_status_lock:
                self._scan_update(completed=self._scan_status.get("completed", 0) + 1)

    def _scan_issue(self, message: str) -> None:
        if getattr(self, "_scan_jobs", None) is not None:
            with self._scan_status_lock:
                issues = list(dict.fromkeys([*self._scan_status.get("issues", []), message]))[:5]
                self._scan_update(errors=self._scan_status.get("errors", 0) + 1, issues=issues)

    def _check_scan_stopped(self) -> None:
        if getattr(self, "_scan_jobs", None) is not None and self._stop_event.is_set():
            raise ScanInterrupted()

    def _checkpoint(self) -> None:
        if getattr(self, "_scan_jobs", None) is not None:
            self._check_scan_stopped()
            self._save_jobs(self._scan_jobs)

    def _persist_job(self, job: dict) -> None:
        self._check_scan_stopped()
        jobs = self._scan_jobs if getattr(self, "_scan_jobs", None) is not None else self.get_data(self.JOBS_KEY) or {}
        jobs[job["target_hash"]] = job
        self._save_jobs(jobs)

    def get_job(self, target_hash: str) -> schemas.Response:
        """按目标 InfoHash 返回单个保种任务。"""

        jobs = self.get_data(self.JOBS_KEY) or {}
        job = jobs.get(str(target_hash or "").lower())
        if not job:
            return schemas.Response(success=False, message="保种任务不存在")
        return schemas.Response(success=True, data=self._job_view(job))

    def download_candidate(
        self,
        target_hash: str,
        payload: CandidateSelectionPayload,
    ) -> schemas.Response:
        """重新验证候选后下载用户选择的来源种子。"""

        if not self._lock.acquire(blocking=False):
            return schemas.Response(success=False, message="插件正在执行其他操作，请稍后重试")
        try:
            jobs = self.get_data(self.JOBS_KEY) or {}
            job = jobs.get(str(target_hash or "").lower())
            if not job:
                return schemas.Response(success=False, message="保种任务不存在")
            if job.get("state") in self.DOWNLOAD_STARTED_STATES:
                if job.get("state") == "SOURCE_SUBMITTING":
                    return schemas.Response(success=False, message="下载提交结果待确认，请先检查 qBittorrent，勿重复添加")
                if payload.candidate_id == job.get("selected_candidate_id"):
                    return schemas.Response(success=True, data=self._job_view(job))
                return schemas.Response(success=False, message="任务已经选择了其他来源")
            is_target = payload.candidate_id == self._target_candidate_id(job)
            if is_target and job.get("target_site_id") and job.get("state") in self.TARGET_SELECTABLE_STATES:
                if self._at_download_capacity() and not self._get_torrent(job["target_hash"]):
                    return schemas.Response(success=False, message="达到稀缺保种同时下载上限")
                candidate, reason = self._target_source(job)
                if not candidate:
                    return schemas.Response(success=False, message=reason)
            elif job.get("state") != "AWAITING_SELECTION" or is_target:
                return schemas.Response(success=False, message="当前任务不允许选择来源")
            else:
                candidate_record = next(
                    (
                        item for item in job.get("candidates") or []
                        if item.get("candidate_id") == payload.candidate_id
                    ),
                    None,
                )
                if not candidate_record:
                    return schemas.Response(success=False, message="候选来源不存在或已经过期")
                if candidate_record.get("eligible") is False:
                    return schemas.Response(success=False, message="该来源未通过下载规则，请调整配置后重新匹配")
                if self._at_download_capacity():
                    return schemas.Response(success=False, message="达到稀缺保种同时下载上限")
                match = IyuuMatch(
                    candidate_record.get("iyuu_sid"),
                    str(candidate_record.get("torrent_id") or ""),
                    str(candidate_record.get("expected_hash") or ""),
                )
                candidates, _ = self._probe_sources([match], job.get("title") or "")
                ranked = ranked_sources(candidates, self._minimum_seeders, self._allowed_promotions)
                candidate = next(
                    (
                        item for item in ranked
                        if self._candidate_id(item) == payload.candidate_id
                    ),
                    None,
                )
                if not candidate:
                    return schemas.Response(success=False, message="来源状态已变化，请重新匹配后再试")
            kind = promotion_kind(candidate.download_factor)
            confirmed = (kind == UNKNOWN and payload.confirm_unknown) or (
                kind == NON_FREE and payload.confirmed_download_factor == candidate.download_factor
            )
            if self._confirm_download_risk and kind != FREE and not confirmed and not self._get_torrent(candidate.match.info_hash):
                self._save_jobs(jobs)
                return schemas.Response(success=False, message="所选种子非免费或促销未知，请确认后下载", data={
                    "confirmation_required": True,
                    "candidate_id": payload.candidate_id,
                    "title": job.get("title"),
                    "site_name": candidate.site_name,
                    "promotion": kind,
                    "download_factor": candidate.download_factor if kind == NON_FREE else None,
                })
            # 只有确认了本次最新促销，才记住“不再提醒”；取消或过期确认不会关闭提醒。
            if payload.skip_future_risk_confirmation and confirmed and self._confirm_download_risk:
                self.update_config({**self._current_config(), "confirm_download_risk": False})
                self._confirm_download_risk = False
            job["selected_candidate_id"] = payload.candidate_id
            try:
                success, reason = self._start_source(candidate, job)
            except DownloadSubmissionUncertain:
                self._save_jobs(jobs)
                return schemas.Response(success=False, message=job["reason"])
            if not success:
                job["selected_candidate_id"] = None
                self._finish(job, "FAILED_TARGET_TORRENT" if is_target else "FAILED_SOURCE_DOWNLOAD", reason)
                self._save_jobs(jobs)
                return schemas.Response(success=False, message=reason)
            self._save_jobs(jobs)
            return schemas.Response(success=True, data=self._job_view(job))
        finally:
            self._lock.release()

    def retry_job(self, target_hash: str) -> schemas.Response:
        """重新查询指定任务的 IYUU 映射和来源站状态。"""

        if not self._lock.acquire(blocking=False):
            return schemas.Response(success=False, message="插件正在执行其他操作，请稍后重试")
        try:
            jobs = self.get_data(self.JOBS_KEY) or {}
            job = jobs.get(str(target_hash or "").lower())
            if not job:
                return schemas.Response(success=False, message="保种任务不存在")
            if job.get("state") in self.DOWNLOAD_STARTED_STATES:
                return schemas.Response(success=False, message="当前任务正在下载或已经进入辅种流程")
            job.update({
                "state": "MATCHING",
                "reason": None,
                "candidates": [],
                "selected_candidate_id": None,
                "retry_count": 0,
                "next_retry_at": None,
            })
            self._save_jobs(jobs)
            self._find_and_download(job)
            self._save_jobs(jobs)
            failed = job.get("state") in {"WAITING_IYUU_RETRY", "WAITING_SOURCE_RETRY", "FAILED_MATCHING", "FAILED_SOURCE_DOWNLOAD", "SOURCE_SUBMITTING"}
            return schemas.Response(success=not failed, message=job.get("reason") if failed else None,
                                    data=self._job_view(job))
        finally:
            self._lock.release()

    def ignore_job(self, target_hash: str) -> schemas.Response:
        """将尚未进入下载流程的任务标记为已忽略。"""

        if not self._lock.acquire(blocking=False):
            return schemas.Response(success=False, message="插件正在执行其他操作，请稍后重试")
        try:
            jobs = self.get_data(self.JOBS_KEY) or {}
            job = jobs.get(str(target_hash or "").lower())
            if not job:
                return schemas.Response(success=False, message="保种任务不存在")
            if job.get("state") in self.DOWNLOAD_STARTED_STATES:
                return schemas.Response(success=False, message="当前任务正在下载或已经进入辅种流程")
            self._finish(job, "IGNORED", "用户忽略")
            self._save_jobs(jobs)
            return schemas.Response(success=True, data=self._job_view(job))
        finally:
            self._lock.release()

    def get_service(self) -> List[Dict[str, Any]]:
        """注册周期扫描，并支持保存配置后立即执行一次。"""

        services: List[Dict[str, Any]] = []
        valid = self._valid_config(log_error=self._enabled or self._run_once)
        if self._enabled and valid:
            try:
                trigger = CronTrigger.from_crontab(self._cron)
            except ValueError as err:
                logger.error(f"稀缺保种 CRON 无效：{str(err)}")
            else:
                services.append({
                    "id": "SeedRescue.Scan",
                    "name": "稀缺保种RSS扫描",
                    "trigger": trigger,
                    "func": self.scan,
                    "kwargs": {},
                })
        if self._run_once and valid:
            services.append({
                "id": "SeedRescue.RunOnce",
                "name": "稀缺保种立即扫描",
                "trigger": "date",
                "func": self.scan,
                "kwargs": {"run_date": datetime.now().astimezone() + timedelta(seconds=3)},
            })
        return services

    def stop_service(self) -> None:
        """请求后台扫描在安全点退出，不中断正在进行的下载器请求。"""

        self._ensure_scan_runtime()
        with self._scan_status_lock:
            if self._scan_status.get("state") == "running":
                self._scan_update(state="interrupted", finished_at=self._now(),
                                  message="扫描已停止，未完成的匹配将在下次扫描恢复")
            self._stop_event.set()
        worker = self._scan_thread
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=10)

    def _valid_config(self, log_error: bool = False) -> bool:
        checks = [
            (self._iyuu is not None, "请安装并配置 IYUU自动辅种插件，同时填写 IYUU Token"),
            (PluginManager().get_plugin_state("IYUUAutoSeed"), "请启用并正确配置 IYUU自动辅种插件"),
            (bool(self._target_site_id), "请选择目标站点"),
            (bool(self._rss_urls), "请填写至少一个目标站 RSS"),
            (bool(self._source_site_ids), "请选择至少一个来源站点"),
            (bool(self._allowed_promotions), "免费和非免费至少选择一项"),
            (bool(self._downloader_name), "请选择 qBittorrent 下载器"),
        ]
        for passed, message in checks:
            if not passed:
                if log_error:
                    logger.error(f"稀缺保种配置无效：{message}")
                return False
        service = DownloaderHelper().get_service(name=self._downloader_name)
        if not service or not service.instance or service.type != "qbittorrent":
            if log_error:
                logger.error("稀缺保种配置无效：当前版本仅支持已连接的 qBittorrent")
            return False
        if getattr(service.instance, "is_inactive", lambda: False)():
            if log_error:
                logger.error("稀缺保种配置无效：qBittorrent 当前未连接")
            return False
        return True

    def scan(self) -> None:
        """供宿主调度器同步执行，与手动后台扫描共享互斥名额。"""

        if not self._lock.acquire(blocking=False):
            logger.info("稀缺保种任务仍在运行，本轮跳过")
            return
        try:
            self._begin_scan()
            self._scan_thread = threading.current_thread()
        except Exception:
            self._lock.release()
            raise
        self._run_scan()

    def _run_scan(self) -> None:
        jobs = None
        try:
            if not self._valid_config(log_error=True):
                self._scan_update(state="failed", message="插件配置不完整或下载器不可用")
                return
            jobs = self.get_data(self.JOBS_KEY) or {}
            self._scan_jobs = jobs
            self._check_scan_stopped()
            self._scan_stage("reconcile", 1)
            self._reconcile_jobs(jobs)
            self._scan_advance()
            self._checkpoint()
            self._scan_stage("recovery")
            self._resume_waiting_jobs(jobs)
            self._checkpoint()
            target_site = SiteOper().get(self._target_site_id)
            if not target_site:
                self._scan_update(state="failed", message="稀缺保种目标站点不存在")
                return
            jobs_by_feed = {
                job["feed_key"]: job for job in jobs.values()
                if job.get("feed_key") and job.get("target_site_id") == self._target_site_id
            }
            jobs_by_id = {
                str(job["target_torrent_id"]): job for job in jobs.values()
                if job.get("target_torrent_id") and job.get("target_site_id") == self._target_site_id
            }
            source_keys = self._rss_source_keys()
            snapshots = {
                key: value for key, value in (self.get_data(self.RSS_SNAPSHOTS_KEY) or {}).items()
                if key in source_keys
            }
            scan_at = self._now()
            new_jobs: List[dict] = []
            failed_feeds = 0
            self._scan_stage("rss", len(self._rss_urls))
            for source_key, rss_url in zip(source_keys, self._rss_urls):
                self._check_scan_stopped()
                try:
                    items = RssHelper().parse(
                        rss_url,
                        proxy=bool(getattr(target_site, "proxy", False)),
                        timeout=int(getattr(target_site, "timeout", 30) or 30),
                        ua=getattr(target_site, "ua", None) or settings.USER_AGENT,
                    )
                except Exception:
                    items = False
                if not isinstance(items, list):
                    failed_feeds += 1
                    self._scan_issue("RSS 拉取失败，保留上次成功记录")
                    previous = dict(snapshots.get(source_key) or {})
                    previous.update(last_attempt_at=scan_at, error="RSS 拉取失败，保留上次成功记录")
                    snapshots[source_key] = previous
                    logger.warning("稀缺保种 RSS 获取失败，保留上次成功记录")
                    self._scan_advance()
                    continue
                snapshots[source_key] = {
                    "last_attempt_at": scan_at,
                    "last_success_at": scan_at,
                    "error": None,
                    "item_keys": [feed_key(item.get("enclosure"), item.get("link"), item.get("title")) for item in items],
                    "torrent_ids": [
                        torrent_id for item in items
                        if (torrent_id := extract_torrent_id(item.get("link") or item.get("enclosure")))
                    ],
                }
                new_count = 0
                for item in items:
                    self._check_scan_stopped()
                    item_key = feed_key(item.get("enclosure"), item.get("link"), item.get("title"))
                    torrent_id = extract_torrent_id(item.get("link") or item.get("enclosure"))
                    existing = jobs_by_feed.get(item_key) or jobs_by_id.get(torrent_id)
                    if existing:
                        self._set_target_identity(existing, item, target_site)
                        existing["feed_key"] = item_key
                        jobs_by_feed[item_key] = existing
                        continue
                    if self._initial_limit is not None and new_count >= self._initial_limit:
                        continue
                    new_count += 1
                    job = self._create_job(item, item_key, target_site)
                    if not job:
                        self._scan_issue("部分 RSS 种子元数据获取失败，将在后续扫描重试")
                        continue
                    if job["target_hash"] in jobs:
                        existing = jobs[job["target_hash"]]
                        self._set_target_identity(existing, item, target_site)
                        job = existing
                    else:
                        jobs[job["target_hash"]] = job
                        new_jobs.append(job)
                    jobs_by_feed[item_key] = job
                    job["feed_key"] = item_key
                    if job.get("target_torrent_id"):
                        jobs_by_id[str(job["target_torrent_id"])] = job
                    self._checkpoint()
                self._scan_advance()
            self._check_scan_stopped()
            self._update_rss_presence(jobs, snapshots)
            target_jobs = self._select_target_refresh_jobs(jobs)
            self.save_data(self.RSS_SNAPSHOTS_KEY, snapshots)
            self._save_jobs(jobs)
            self._check_scan_stopped()
            self._scan_stage("matching", len(new_jobs))
            self._find_and_download_jobs(new_jobs)
            self._checkpoint()
            self._check_scan_stopped()
            self._scan_stage("target_stats", len(target_jobs))
            self._refresh_target_jobs(target_jobs, target_site)
            self._save_jobs(jobs)
            self._check_scan_stopped()
            result = "failed" if failed_feeds == len(self._rss_urls) else (
                "partial" if self._get_scan_status().get("errors") else "success"
            )
            self._scan_update(state=result, message={
                "success": "扫描完成", "partial": "扫描完成，部分请求失败，详见提示及任务重试时间",
                "failed": "全部 RSS 拉取失败，已保留上次成功记录",
            }[result])
        except ScanInterrupted:
            self._scan_update(state="interrupted", message="扫描已中断，未完成的匹配将在下次扫描恢复")
        except Exception as err:
            logger.error(f"稀缺保种扫描异常：{type(err).__name__}")
            self._scan_update(state="failed", message="扫描异常，已完成的阶段将保留；未完成的匹配可重试")
        finally:
            try:
                try:
                    if jobs is not None:
                        self._save_jobs(jobs)
                except Exception as err:
                    logger.error(f"稀缺保种任务保存失败：{type(err).__name__}")
                    self._scan_update(state="failed", message="任务保存失败，请检查存储后重试扫描")
                self._scan_update(finished_at=self._now())
            finally:
                self._scan_jobs = None
                self._scan_thread = None
                self._lock.release()

    def _rss_source_keys(self) -> List[str]:
        """订阅按站点和 RSS 地址摘要区分，不保存含凭据的 URL。"""

        return [
            f"{self._target_site_id}:{feed_key(url, None, None)}"
            for url in self._rss_urls
        ]

    def _update_rss_presence(self, jobs: dict, snapshots: dict) -> None:
        """合并各订阅最近一次成功快照，独立于下载状态维护当前/历史归属。"""

        active = [snapshots.get(key, {}) for key in self._rss_source_keys()]
        complete = bool(active) and all(snapshot.get("last_success_at") for snapshot in active)
        item_seen: Dict[str, str] = {}
        id_seen: Dict[str, str] = {}
        for snapshot in active:
            seen_at = snapshot.get("last_success_at")
            if not seen_at:
                continue
            for item_key in snapshot.get("item_keys") or []:
                item_seen[item_key] = max(item_seen.get(item_key, ""), seen_at)
            for torrent_id in snapshot.get("torrent_ids") or []:
                id_seen[torrent_id] = max(id_seen.get(torrent_id, ""), seen_at)
        now = self._now()
        for job in jobs.values():
            same_site = job.get("target_site_id") == self._target_site_id
            last_seen = max(
                item_seen.get(job.get("feed_key"), ""),
                id_seen.get(str(job.get("target_torrent_id") or ""), ""),
            ) if same_site else ""
            if last_seen:
                job.update(rss_current=True, rss_last_seen_at=last_seen, rss_archived_at=None)
            elif complete or not same_site:
                if job.get("rss_current") is not False:
                    job["rss_archived_at"] = now
                job["rss_current"] = False

    def _create_job(self, item: dict, item_key: str, target_site: Any) -> Optional[dict]:
        enclosure = str(item.get("enclosure") or "").strip()
        if not enclosure:
            logger.warning(f"RSS 种子缺少下载链接：{item.get('title') or '未知标题'}")
            return None
        _, content, _, _, error = TorrentHelper().download_torrent(
            url=enclosure,
            cookie=getattr(target_site, "cookie", None),
            ua=getattr(target_site, "ua", None) or settings.USER_AGENT,
            proxy=bool(getattr(target_site, "proxy", False)),
        )
        if not isinstance(content, bytes):
            logger.warning(f"目标种子元数据下载失败：{item.get('title')}，{error or '未知错误'}")
            return None
        try:
            target_hash = info_hash_from_torrent(content)
        except ValueError as err:
            logger.warning(f"目标种子元数据无效：{item.get('title')}，{str(err)}")
            return None
        job = {
            "feed_key": item_key,
            "target_hash": target_hash,
            "target_site_id": self._target_site_id,
            "title": str(item.get("title") or target_hash),
            "state": "MATCHING",
            "created_at": self._now(),
            "updated_at": self._now(),
            "source_hash": None,
            "source_site_id": None,
            "source_site_name": None,
            "source_seeders": None,
            "promotion": None,
            "reason": None,
            "probes": [],
            "candidates": [],
            "selected_candidate_id": None,
        }
        self._set_target_identity(job, item, target_site)
        return job

    def _set_target_identity(self, job: dict, item: dict, target_site: Any) -> None:
        """从 RSS 保存目标种子的站点、详情页和稳定 ID，不保存下载密钥。"""

        link = str(item.get("link") or "").strip()
        enclosure = str(item.get("enclosure") or "").strip()
        job.update({
            "target_site_name": getattr(target_site, "name", None) or str(self._target_site_id),
            "target_torrent_id": extract_torrent_id(link or enclosure),
            "target_page_url": safe_page_url(link),
            "target_size": item.get("size"),
        })

    def _refresh_target_jobs(self, jobs: List[dict], target_site: Any) -> None:
        """以最多两路请求刷新目标站做种、下载和完成数。"""

        domain = getattr(target_site, "domain", None) or StringUtils.get_url_domain(
            getattr(target_site, "url", None)
        )
        jobs = [job for job in jobs if domain and job.get("target_torrent_id")]
        if not jobs:
            return
        with ThreadPoolExecutor(
            max_workers=min(2, len(jobs)),
            thread_name_prefix="seedrescue-target",
        ) as executor:
            futures = {
                executor.submit(self._refresh_target_job, job, domain): job
                for job in jobs
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    future.result()
                except ScanInterrupted:
                    raise
                except Exception:
                    job["target_stats_error"] = "原站信息查询失败，稍后重试"
                    logger.warning(f"目标站数据刷新失败：{job['title']}")
                if job.get("target_stats_error"):
                    self._scan_issue("部分原站信息查询失败，已保留上次有效数据")
                self._scan_advance()

    def _select_target_refresh_jobs(self, jobs: dict) -> List[dict]:
        """缺失促销先补查一次，此后按检查时间轮换，包含已移出 RSS 的记录。"""

        now = datetime.fromisoformat(self._now())
        due = []
        for job in jobs.values():
            if job.get("target_site_id") != self._target_site_id:
                continue
            if not job.get("target_torrent_id"):
                torrent_id = extract_torrent_id(job.get("target_page_url"))
                if not torrent_id:
                    continue
                job["target_torrent_id"] = torrent_id
            missing = promotion_kind(job.get("target_download_factor")) == UNKNOWN
            checked = job.get("target_stats_checked_at")
            last_attempt = checked or (None if missing else job.get("target_stats_updated_at"))
            if last_attempt:
                try:
                    elapsed = now - datetime.fromisoformat(last_attempt)
                    interval = self.TARGET_RETRY_INTERVAL if job.get("target_stats_error") else self.TARGET_REFRESH_INTERVAL
                    if elapsed < interval:
                        continue
                except (TypeError, ValueError):
                    pass
            due.append(job)
        due.sort(key=lambda job: (
            0 if promotion_kind(job.get("target_download_factor")) == UNKNOWN
            and not job.get("target_stats_checked_at") else 1,
            job.get("target_stats_checked_at") or job.get("target_stats_updated_at") or "",
            0 if job.get("rss_current") is True else 1,
            job["target_hash"],
        ))
        return due[:self._initial_limit]

    def _refresh_target_job(self, job: dict, domain: str) -> Optional[Any]:
        """按 RSS 中的种子 ID 精确匹配目标站搜索结果。"""

        target_id = str(job.get("target_torrent_id") or "")
        job["target_stats_checked_at"] = self._now()
        job["target_stats_error"] = "原站信息查询失败，稍后重试"
        if not target_id:
            job["target_stats_error"] = "旧记录缺少原站种子 ID，等待 RSS 再次发现"
            return None
        torrent = None
        for keyword in search_keywords(job.get("title") or ""):
            self._check_scan_stopped()
            rows = TorrentsChain().browse(domain=domain, keyword=keyword) or []
            torrent = next((
                row for row in rows
                if extract_torrent_id(row.page_url or row.enclosure) == target_id
            ), None)
            if torrent:
                break
        if not torrent:
            job["target_stats_error"] = "未在原站搜索结果中找到相同种子 ID，稍后重试"
            return
        if promotion_kind(job.get("target_download_factor")) != UNKNOWN and not job.get("target_promotion_updated_at"):
            job["target_promotion_updated_at"] = job.get("target_stats_updated_at")
        job.update({
            "target_page_url": safe_page_url(torrent.page_url) or job.get("target_page_url"),
            "target_seeders": torrent.seeders,
            "target_peers": torrent.peers,
            "target_grabs": torrent.grabs,
            "target_size": torrent.size or job.get("target_size"),
            "target_stats_updated_at": self._now(),
        })
        factor = getattr(torrent, "downloadvolumefactor", None)
        if promotion_kind(factor) != UNKNOWN:
            job.update(target_download_factor=factor, target_promotion_updated_at=self._now(), target_stats_error=None)
        else:
            job["target_stats_error"] = "原站搜索结果未提供有效促销信息，稍后重试"
        return torrent

    def _target_source(self, job: dict) -> Tuple[Optional[SourceCandidate], str]:
        """按任务保存的目标站和种子 ID 取回原种，旧任务可从 RSS 恢复身份。"""

        torrent = None
        if not self._get_torrent(job["target_hash"]):
            site = SiteOper().get(job["target_site_id"])
            if not site:
                return None, "保种站点不存在，请检查站点配置"
            domain = getattr(site, "domain", None) or StringUtils.get_url_domain(getattr(site, "url", None))
            if domain and job.get("target_torrent_id"):
                try:
                    torrent = self._refresh_target_job(job, domain)
                except Exception:
                    logger.warning("原种站点搜索失败，尝试从目标 RSS 获取")
            if not getattr(torrent, "enclosure", None) and job["target_site_id"] == self._target_site_id:
                for rss_url in self._rss_urls:
                    items = RssHelper().parse(
                        rss_url,
                        proxy=bool(getattr(site, "proxy", False)),
                        timeout=int(getattr(site, "timeout", 30) or 30),
                        ua=getattr(site, "ua", None) or settings.USER_AGENT,
                    )
                    for item in items if isinstance(items, list) else []:
                        item_id = extract_torrent_id(item.get("link") or item.get("enclosure"))
                        same_id = bool(job.get("target_torrent_id")) and item_id == str(job["target_torrent_id"])
                        same_feed = bool(job.get("feed_key")) and job["feed_key"] == feed_key(
                            item.get("enclosure"), item.get("link"), item.get("title"),
                        )
                        if item.get("enclosure") and (same_id or same_feed):
                            self._set_target_identity(job, item, site)
                            torrent = SimpleNamespace(
                                enclosure=item["enclosure"],
                                title=job["title"],
                                site_name=job.get("target_site_name"),
                                site_cookie=getattr(site, "cookie", None),
                                site_ua=getattr(site, "ua", None) or settings.USER_AGENT,
                                site_proxy=bool(getattr(site, "proxy", False)),
                            )
                            break
                    if getattr(torrent, "enclosure", None):
                        break
            if not getattr(torrent, "enclosure", None):
                return None, "未找到保种站点原种的下载链接，请重新扫描 RSS 或检查站点登录状态"
        return SourceCandidate(
            match=IyuuMatch(None, str(job.get("target_torrent_id") or ""), job["target_hash"]),
            site_id=job["target_site_id"],
            site_name=job.get("target_site_name") or "保种站点",
            seeders=job.get("target_seeders"),
            # 展示可保留旧促销，但下载确认只信本次查询；RSS 回退没有实时促销，按未知确认。
            download_factor=getattr(torrent, "downloadvolumefactor", None),
            priority=0,
            torrent=torrent,
        ), ""

    def _find_and_download(self, job: dict) -> None:
        try:
            self._check_scan_stopped()
            seed_list, message = self._iyuu.get_seed_info([job["target_hash"]])
            matches = self._matches_for_job(job, seed_list, message)
            if matches is not None:
                candidates, probes = self._probe_sources(matches, job["title"])
                self._check_scan_stopped()
                self._apply_candidates(job, candidates, probes)
        except ScanInterrupted:
            raise
        except DownloadSubmissionUncertain:
            self._scan_issue("部分下载提交结果待确认，未自动重试添加")
        except Exception:
            if job.get("state") == "SOURCE_SUBMITTING":
                self._scan_issue("部分下载提交结果待确认，未自动重试添加")
            else:
                self._defer_retry(job, "同源匹配或站点查询异常，稍后重试")
        finally:
            self._checkpoint()
            self._scan_advance()

    def _find_and_download_jobs(self, jobs: List[dict]) -> None:
        """批量查询 IYUU，并行探测不同任务的来源站点。"""

        if not jobs:
            return
        if len(jobs) == 1:
            self._find_and_download(jobs[0])
            return
        self._check_scan_stopped()
        try:
            seed_list, message = self._iyuu.get_seed_info([job["target_hash"] for job in jobs])
        except Exception:
            for job in jobs:
                self._defer_retry(job, "IYUU 请求异常，稍后重试", "WAITING_IYUU_RETRY")
                self._scan_advance()
            self._checkpoint()
            return
        pending: List[Tuple[dict, List[IyuuMatch]]] = []
        for job in jobs:
            matches = self._matches_for_job(job, seed_list, message)
            if matches is not None:
                pending.append((job, matches))
            else:
                self._scan_advance()
        self._checkpoint()
        if not pending:
            return
        worker_count = min(4, len(pending))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="seedrescue-probe",
        ) as executor:
            futures = {
                executor.submit(self._probe_sources, matches, job["title"]): job
                for job, matches in pending
            }
            for future in as_completed(futures):
                job = futures[future]
                try:
                    candidates, probes = future.result()
                    self._check_scan_stopped()
                    self._apply_candidates(job, candidates, probes)
                except ScanInterrupted:
                    raise
                except DownloadSubmissionUncertain:
                    self._scan_issue("部分下载提交结果待确认，未自动重试添加")
                except Exception:
                    if job.get("state") == "SOURCE_SUBMITTING":
                        self._scan_issue("部分下载提交结果待确认，未自动重试添加")
                    else:
                        self._defer_retry(job, "来源站查询异常，稍后重试")
                self._checkpoint()
                self._scan_advance()

    def _matches_for_job(
        self,
        job: dict,
        seed_list: Any,
        message: Optional[str],
    ) -> Optional[List[IyuuMatch]]:
        """从一次 IYUU 响应中取出单个任务的映射并更新失败状态。"""

        if seed_list is None and not ("状态码：404" in str(message) and "未查询到可辅种数据" in str(message)):
            self._defer_retry(job, "IYUU 请求失败，稍后重试", "WAITING_IYUU_RETRY")
            return None
        matches = iyuu_matches_for_hash(seed_list, job["target_hash"])
        matches = [match for match in matches if match.info_hash != job["target_hash"]]
        if not matches:
            self._finish(job, "SKIPPED_NO_IYUU_MATCH", message or "IYUU没有返回其他站点同源种子")
            return None
        return matches

    def _apply_candidates(
        self,
        job: dict,
        candidates: List[SourceCandidate],
        probes: List[dict],
    ) -> None:
        """应用来源探测结果，并根据选择模式进入后续状态。"""

        job["probes"] = probes
        ranked = ranked_sources(candidates, self._minimum_seeders, self._allowed_promotions)
        eligible_ids = {self._candidate_id(candidate) for candidate in ranked}
        excluded = [candidate for candidate in candidates if self._candidate_id(candidate) not in eligible_ids]
        job["candidates"] = [{
            **self._candidate_record(candidate),
            "eligible": self._candidate_id(candidate) in eligible_ids,
            "exclusion_reason": self._candidate_exclusion_reason(candidate),
        } for candidate in [*ranked, *excluded]]
        if any(probe.get("error") for probe in probes):
            if not ranked:
                self._defer_retry(job, "部分站点查询失败且暂无符合条件的来源，稍后重试")
                return
            self._scan_issue("部分来源站查询失败，已保留其他站点的可用候选")
        job.update(retry_count=0, next_retry_at=None)
        if not ranked:
            self._finish(
                job,
                "SKIPPED_NO_HEALTHY_SOURCE",
                self._source_rejection_reason(candidates, probes),
            )
            return
        should_wait_for_selection = self._selection_mode == "manual" or (
            self._selection_mode == "hybrid" and len(ranked) > 1
        )
        if should_wait_for_selection:
            self._finish(job, "AWAITING_SELECTION", None)
            return
        if self._at_download_capacity():
            self._finish(job, "WAITING_CAPACITY", "达到稀缺保种同时下载上限")
            return
        errors: List[str] = []
        for candidate in ranked:
            success, reason = self._start_source(candidate, job)
            if success:
                return
            errors.append(f"{candidate.site_name}: {reason}")
        self._finish(job, "FAILED_SOURCE_DOWNLOAD", "；".join(errors) or "来源种子下载失败")
        self._scan_issue("部分来源下载失败，请在任务详情检查")

    def _source_rejection_reason(
        self,
        candidates: List[SourceCandidate],
        probes: List[dict],
    ) -> str:
        """说明已找到的来源为何没有进入可下载候选。"""

        if not candidates:
            unmatched = sum(not probe.get("matched") for probe in probes)
            if unmatched:
                limited = any(probe.get("search_limited") for probe in probes)
                return f"IYUU 返回了 {unmatched} 个来源，但已查搜索范围内未找到对应种子 ID" + (
                    "（已达分页上限，不代表站点没有资源）" if limited else ""
                )
            return "IYUU 返回的来源不在已选择的来源站点中"
        below = sum(
            candidate.seeders is None or candidate.seeders < self._minimum_seeders
            for candidate in candidates
        ) if self._minimum_seeders is not None else 0
        disallowed = Counter(
            promotion_kind(candidate.download_factor)
            for candidate in candidates
            if promotion_kind(candidate.download_factor) not in self._allowed_promotions
        )
        details: List[str] = []
        if below:
            details.append(f"{below} 个未达到最少 {self._minimum_seeders} 人做种")
        if disallowed:
            labels = {FREE: "免费", NON_FREE: "非免费", "unknown": "促销未知"}
            text = "、".join(
                f"{count} 个{labels.get(kind, kind)}" for kind, count in disallowed.items()
            )
            allowed = "、".join(
                labels.get(kind, kind) for kind in (FREE, NON_FREE)
                if kind in self._allowed_promotions
            ) or "无"
            details.append(f"{text}不在允许范围内（当前允许：{allowed}）")
        return f"已精确匹配 {len(candidates)} 个同源来源，但" + "；".join(details or ["均未通过筛选"])

    def _candidate_exclusion_reason(self, candidate: SourceCandidate) -> Optional[str]:
        """逐条解释下载规则，不将已匹配但不达标的来源隐藏。"""

        reasons = []
        if candidate.metadata_status != "ready":
            reasons.append(candidate.metadata_error or "IYUU 已收录，详情待获取")
        if self._minimum_seeders is not None:
            if candidate.seeders is None:
                reasons.append(f"做种人数未知，至少需要 {self._minimum_seeders} 人")
            elif candidate.seeders < self._minimum_seeders:
                reasons.append(f"做种 {candidate.seeders} 人，少于最低 {self._minimum_seeders} 人")
        kind = promotion_kind(candidate.download_factor)
        if kind not in self._allowed_promotions:
            label = {FREE: "免费", NON_FREE: "非免费", UNKNOWN: "促销未知"}[kind]
            reasons.append(f"{label}，未通过促销规则")
        return "；".join(reasons) or None

    def _probe_sources(
        self,
        matches: List[IyuuMatch],
        title: str,
    ) -> Tuple[List[SourceCandidate], List[dict]]:
        source_priority = {site_id: index for index, site_id in enumerate(self._source_site_ids)}
        grouped: Dict[str, list] = {}
        for index, match in enumerate(matches):
            base_url, download_page = self._iyuu.get_torrent_url(match.sid)
            domain = StringUtils.get_url_domain(base_url) if base_url else None
            site = SitesHelper().get_indexer(domain) if domain else None
            if not site or site.get("id") not in source_priority:
                continue
            # IYUU 的经典 download.php 模板也可识别 NexusPHP（部分宿主未提供 schema）。
            site = {**site, "_seedrescue_nexus": "download.php?" in str(download_page or "")}
            grouped.setdefault(domain, []).append((index, match, site))
        if not grouped:
            return [], []
        ordered: List[Tuple[int, Optional[SourceCandidate], dict]] = []
        worker_count = min(4, len(grouped))
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="seedrescue-site",
        ) as executor:
            futures = {
                executor.submit(
                    self._probe_domain,
                    domain,
                    entries,
                    title,
                    source_priority,
                ): domain
                for domain, entries in grouped.items()
            }
            for future in as_completed(futures):
                try:
                    ordered.extend(future.result())
                except ScanInterrupted:
                    raise
                except Exception:
                    for index, match, site in grouped[futures[future]]:
                        candidate = self._pending_candidate(match, site, title, source_priority, "站点查询异常")
                        ordered.append((index, candidate, {
                            "site_id": site.get("id"), "site_name": site.get("name"),
                            "matched": True, "metadata_status": "unavailable", "torrent_id": match.torrent_id,
                            "page_url": detail_url(site, match.torrent_id),
                            "error": "站点查询异常", "promotion": UNKNOWN,
                        }))
        ordered.sort(key=lambda item: item[0])
        candidates = [item[1] for item in ordered if item[1] is not None]
        probes = [item[2] for item in ordered]
        return candidates, probes

    def _probe_domain(
        self,
        domain: str,
        entries: list,
        title: str,
        source_priority: Dict[int, int],
    ) -> List[Tuple[int, Optional[SourceCandidate], dict]]:
        """优先按 ID 取详情；仅未适配/字段不完整时按名称搜索兜底。"""

        torrents: Dict[str, Any] = {}
        details: Dict[str, DetailResult] = {}
        methods: Dict[str, str] = {}
        search_count = 0
        keywords = search_keywords(title)
        stable_keywords = keywords[:-1] or keywords
        # 优先较短关键词的首页，再交替翻页，完整发布名只作最后兜底。
        queries = [(keyword, page) for page in range(self.MAX_SOURCE_PAGES) for keyword in stable_keywords]
        if keywords and keywords[-1] not in stable_keywords:
            queries.append((keywords[-1], 0))
        exhausted = set()
        seen_pages: Dict[str, set] = {}
        searched_pages: Dict[str, int] = {}
        search_error = None
        if not hasattr(self, "_source_probe_slots"):
            self._source_probe_slots = threading.BoundedSemaphore(6)
        with self._site_search_lock(domain):
            with self._source_probe_slots:
                for _, match, site in entries:
                    if match.torrent_id in details:
                        continue
                    self._check_scan_stopped()
                    result = self._fetch_source_detail(domain, site, match.torrent_id)
                    details[match.torrent_id] = result
                    if result.torrent:
                        torrents[match.torrent_id] = self._detail_torrent(result.torrent, site)
                        methods[match.torrent_id] = "detail"
                # 连接、认证、限流失败时不追加最多 8 次搜索，交给已有退避机制。
                fallback_ids = {tid for tid, result in details.items() if result.status in {"unsupported", "partial"}}
                found_fallback = set()
                for keyword, page in queries:
                    if fallback_ids.issubset(found_fallback):
                        break
                    if keyword in exhausted:
                        continue
                    if search_count >= self.MAX_SOURCE_SEARCHES:
                        break
                    self._check_scan_stopped()
                    search_count += 1
                    try:
                        rows = TorrentsChain().browse(domain=domain, keyword=keyword, page=page) or []
                    except ScanInterrupted:
                        raise
                    except Exception:
                        search_error = "站点查询异常"
                        break
                    searched_pages[keyword] = page
                    fingerprint = frozenset(str(row.page_url or row.enclosure or "") for row in rows)
                    previous_pages = seen_pages.setdefault(keyword, set())
                    if not rows or fingerprint in previous_pages:
                        exhausted.add(keyword)
                        continue
                    previous_pages.add(fingerprint)
                    for row in rows:
                        torrent_id = extract_torrent_id(row.page_url or row.enclosure)
                        if torrent_id in fallback_ids and torrent_id not in found_fallback:
                            torrents[torrent_id] = row
                            methods[torrent_id] = "search"
                            found_fallback.add(torrent_id)
                    if fallback_ids.issubset(found_fallback):
                        break
        search_limited = search_count >= self.MAX_SOURCE_SEARCHES or any(
            page >= self.MAX_SOURCE_PAGES - 1 and keyword not in exhausted
            for keyword, page in searched_pages.items()
        )
        results: List[Tuple[int, Optional[SourceCandidate], dict]] = []
        for index, match, site in entries:
            torrent = torrents.get(match.torrent_id)
            result = details[match.torrent_id]
            ready = methods.get(match.torrent_id) == "search" or result.status == "ready" or (
                result.status == "partial" and self._minimum_seeders is None
                and getattr(torrent, "downloadvolumefactor", None) is not None
            )
            error = None if ready else search_error or (
                "详情及兜底搜索未取得对应 ID 的完整信息，可重新匹配重试"
                if search_count else result.error or "详情获取失败，可重新匹配重试"
            )
            seeders = torrent.seeders if torrent else None
            factor = torrent.downloadvolumefactor if torrent else None
            probe = {
                "site_id": site.get("id"),
                "site_name": site.get("name"),
                "title": getattr(torrent, "title", None) if torrent else None,
                "page_url": safe_page_url(getattr(torrent, "page_url", None)) if torrent else detail_url(site, match.torrent_id),
                "seeders": seeders,
                "promotion": promotion_kind(factor),
                "matched": True,
                "metadata_status": "ready" if ready else "unavailable",
                "lookup_method": methods.get(match.torrent_id),
                "searches": search_count,
                "torrent_id": match.torrent_id,
                "search_limited": not ready and search_limited,
            }
            if error:
                probe["error"] = error
            candidate = self._pending_candidate(match, site, title, source_priority, error)
            if torrent:
                candidate = SourceCandidate(
                    match=match,
                    site_id=site.get("id"),
                    site_name=site.get("name") or domain,
                    seeders=seeders,
                    download_factor=factor,
                    priority=source_priority[site.get("id")],
                    torrent=torrent,
                    metadata_status=probe["metadata_status"],
                    metadata_error=error,
                    lookup_method=methods.get(match.torrent_id),
                )
            results.append((index, candidate, probe))
        return results

    @staticmethod
    def _fetch_source_detail(domain: str, site: dict, torrent_id: str) -> DetailResult:
        if detail_url(site, torrent_id):
            limited, _ = SitesHelper().check(domain)
            if limited:
                return DetailResult(status="unavailable", error="站点流控中，稍后重试详情")
        return fetch_detail(site, torrent_id, RequestUtils,
                            proxy=getattr(settings, "PROXY", None), user_agent=settings.USER_AGENT)

    @staticmethod
    def _detail_torrent(fields: dict, site: dict) -> Any:
        """下载地址及凭据仅保留在运行时，不进入候选记录或前端。"""
        return SimpleNamespace(**fields, site=site.get("id"), site_name=site.get("name"),
                               site_cookie=site.get("cookie"), site_ua=site.get("ua") or settings.USER_AGENT,
                               site_proxy=bool(site.get("proxy")))

    def _pending_candidate(self, match: IyuuMatch, site: dict, title: str,
                           priority: dict, error: Optional[str]) -> SourceCandidate:
        return SourceCandidate(match, site["id"], site.get("name") or "来源站", None, None,
                               priority[site["id"]],
                               SimpleNamespace(title=title, page_url=detail_url(site, match.torrent_id)),
                               "unavailable", error)

    def _site_search_lock(self, domain: str) -> threading.Lock:
        """同一站点串行检索，不同站点允许并发，避免触发站点流控。"""

        if not hasattr(self, "_site_search_locks"):
            self._site_search_locks = {}
            self._site_search_locks_guard = threading.Lock()
        with self._site_search_locks_guard:
            return self._site_search_locks.setdefault(domain, threading.Lock())

    def _start_source(self, candidate: SourceCandidate, job: dict) -> Tuple[bool, str]:
        self._check_scan_stopped()
        is_target = candidate.match.info_hash == job["target_hash"] and candidate.site_id == job.get("target_site_id")
        downloading_state = "TARGET_DOWNLOADING" if is_target else "SOURCE_DOWNLOADING"
        existing = self._get_torrent(candidate.match.info_hash)
        if existing:
            self._set_source_job(job, candidate)
            state, reason = target_torrent_status(existing) if is_target else (
                "WAITING_IYUU" if torrent_is_complete(existing) else downloading_state, "来源种子已存在于下载器"
            )
            self._finish(
                job,
                state,
                reason,
            )
            return True, ""
        torrent = candidate.torrent
        if not getattr(torrent, "enclosure", None):
            return False, "来源种子缺少下载链接"
        if torrent.enclosure.startswith("["):
            content, _, _ = DownloadChain().download_torrent(torrent)
            error = "站点动态下载链接解析失败"
        else:
            _, content, _, _, error = TorrentHelper().download_torrent(
                url=torrent.enclosure,
                cookie=torrent.site_cookie,
                ua=torrent.site_ua or settings.USER_AGENT,
                proxy=bool(torrent.site_proxy),
            )
        if not isinstance(content, bytes):
            return False, error or "未取得种子文件"
        try:
            actual_hash = info_hash_from_torrent(content)
        except ValueError as err:
            return False, str(err)
        if actual_hash.lower() != candidate.match.info_hash.lower():
            return False, "下载种子Hash与保种原种不一致" if is_target else "下载种子Hash与IYUU映射不一致"
        service = DownloaderHelper().get_service(name=self._downloader_name)
        if not service:
            return False, "下载器不可用"
        self._check_scan_stopped()
        # 先保存提交意图：进程中断或网络超时后只核对同一 Hash，不另选来源重复添加。
        self._set_source_job(job, candidate)
        self._finish(job, "SOURCE_SUBMITTING", "下载提交待确认")
        self._persist_job(job)
        try:
            add_result = service.instance.add_torrent(
                content=content,
                download_dir=self._save_path,
                category=self.CATEGORY,
                tag=[self.GLOBAL_TAG],
            )
        except Exception as err:
            job["reason"] = "下载提交结果未知，后续扫描将核对同一 Hash；请先检查 qBittorrent，勿重复添加"
            self._persist_job(job)
            raise DownloadSubmissionUncertain() from err
        added = add_result[0] if isinstance(add_result, tuple) else bool(add_result)
        if not added:
            # 宿主 qB 封装会把网络超时也转换成 False，不能据此断定没有提交成功。
            job["reason"] = "下载器未确认添加结果，后续扫描将核对同一 Hash；请先检查 qBittorrent，勿重复添加"
            self._persist_job(job)
            raise DownloadSubmissionUncertain()
        self._set_source_job(job, candidate)
        self._finish(job, downloading_state, None)
        logger.info(
            f"稀缺保种从 {candidate.site_name} 下载：{job['title']}，"
            f"做种人数 {candidate.seeders}，促销 {promotion_kind(candidate.download_factor)}"
        )
        return True, ""

    def _set_source_job(self, job: dict, candidate: SourceCandidate) -> None:
        """记录任务实际选择的来源种子。"""

        job.update({
            "selected_candidate_id": (
                self._target_candidate_id(job)
                if candidate.match.info_hash == job["target_hash"] and candidate.site_id == job.get("target_site_id")
                else self._candidate_id(candidate)
            ),
            "source_hash": candidate.match.info_hash,
            "source_site_id": candidate.site_id,
            "source_site_name": candidate.site_name,
            "source_seeders": candidate.seeders,
            "promotion": promotion_kind(candidate.download_factor),
        })

    def _resume_waiting_jobs(self, jobs: dict) -> None:
        pending = []
        for job in jobs.values():
            self._check_scan_stopped()
            state = job.get("state")
            if state in {"MATCHING", "WAITING_IYUU_RETRY", "WAITING_SOURCE_RETRY"} or (
                state == "SKIPPED_NO_IYUU_MATCH"
                and self._retryable_iyuu_error(job.get("reason"))
            ):
                next_retry = job.get("next_retry_at")
                if next_retry:
                    try:
                        if datetime.fromisoformat(next_retry) > datetime.fromisoformat(self._now()):
                            continue
                    except (TypeError, ValueError):
                        pass
                pending.append(job)
            elif state == "WAITING_CAPACITY":
                if self._at_download_capacity():
                    continue
                pending.append(job)
        self._scan_stage("recovery", len(pending))
        # 顺序恢复，避免一次性把排队任务全部重新探测；每条完成即保存。
        for job in pending:
            if job.get("state") == "WAITING_CAPACITY" and self._at_download_capacity():
                continue
            self._find_and_download(job)

    def _defer_retry(self, job: dict, reason: str, state: str = "WAITING_SOURCE_RETRY") -> None:
        attempts = int(job.get("retry_count") or 0) + 1
        job["retry_count"] = attempts
        job["next_retry_at"] = None if attempts >= self.MAX_AUTO_RETRIES else (
            datetime.fromisoformat(self._now()) + timedelta(minutes=min(5 * 2 ** (attempts - 1), 360))
        ).isoformat()
        self._finish(job, "FAILED_MATCHING" if attempts >= self.MAX_AUTO_RETRIES else state,
                     reason + ("；已达到自动重试上限，可手动重新匹配" if attempts >= self.MAX_AUTO_RETRIES else ""))
        self._scan_issue(reason)

    @staticmethod
    def _retryable_iyuu_error(message: Optional[str]) -> bool:
        message = str(message or "")
        return (
            "请求IYUU失败" in message
            and not ("状态码：404" in message and "未查询到可辅种数据" in message)
        )

    def _reconcile_jobs(self, jobs: dict) -> None:
        for job in jobs.values():
            if job.get("state") not in self.ACTIVE_STATES:
                continue
            target = self._get_torrent(job.get("target_hash"))
            if target:
                state, reason = target_torrent_status(target)
                self._finish(job, state, reason)
                continue
            source = self._get_torrent(job.get("source_hash"))
            if source and torrent_is_complete(source):
                self._finish(job, "WAITING_IYUU", "来源下载完成，等待IYUU添加目标站种子")
            elif source:
                self._finish(job, "SOURCE_DOWNLOADING", None)

    def _get_torrent(self, info_hash: Optional[str]) -> Any:
        if not info_hash:
            return None
        service = DownloaderHelper().get_service(name=self._downloader_name)
        if not service:
            return None
        torrents, error = service.instance.get_torrents(ids=[info_hash])
        return torrents[0] if not error and torrents else None

    def _at_download_capacity(self) -> bool:
        if self._max_download_count is None:
            return False
        count = self._downloading_count()
        return count is None or count >= self._max_download_count

    def _downloading_count(self) -> Optional[int]:
        service = DownloaderHelper().get_service(name=self._downloader_name)
        if not service:
            return None
        torrents = service.instance.get_downloading_torrents(tags=self.GLOBAL_TAG)
        return None if torrents is None else len(torrents)

    def _finish(self, job: dict, state: str, reason: Optional[str]) -> None:
        changed = job.get("state") != state or job.get("reason") != reason
        job["state"] = state
        job["reason"] = reason
        job["updated_at"] = self._now()
        if changed and state in self.TERMINAL_STATES and self._notify:
            self._notify_job(job)

    def _notify_job(self, job: dict) -> None:
        state = job.get("state")
        if state == "TARGET_SEEDING":
            title = "【稀缺保种成功】"
        elif state.startswith("SKIPPED"):
            title = "【稀缺保种跳过】"
        else:
            title = "【稀缺保种失败】"
        self.post_message(
            mtype=NotificationType.SiteMessage,
            title=title,
            text=(
                f"种子：{job.get('title')}\n"
                f"状态：{state}\n"
                f"来源：{job.get('source_site_name') or '无'}\n"
                f"原因：{job.get('reason') or '无'}"
            ),
        )

    def _save_jobs(self, jobs: dict) -> None:
        """保留全部当前/运行中任务，以及最近 1000 条其他历史记录。"""

        if getattr(self, "_scan_jobs", None) is jobs and self._stop_event.is_set():
            return
        if len(jobs) > 1000:
            retained = {
                key: job for key, job in jobs.items()
                if job.get("rss_current") is True
                or job.get("state") in self.DOWNLOAD_STARTED_STATES - {"TARGET_SEEDING"}
                or job.get("state") in {"MATCHING", "WAITING_IYUU_RETRY", "WAITING_SOURCE_RETRY", "WAITING_CAPACITY"}
            }
            history = sorted(
                ((key, job) for key, job in jobs.items() if key not in retained),
                key=lambda item: item[1].get("rss_archived_at") or item[1].get("created_at") or "",
                reverse=True,
            )
            jobs = {**retained, **dict(history[:1000])}
        self.save_data(self.JOBS_KEY, jobs)

    @staticmethod
    def _now() -> str:
        """返回包含本地时区的秒级时间字符串。"""

        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _candidate_id(candidate: SourceCandidate) -> str:
        """生成只由服务端候选信息构成的稳定标识。"""

        return ":".join((
            str(candidate.site_id),
            str(candidate.match.torrent_id),
            str(candidate.match.info_hash).lower(),
        ))

    def _candidate_record(self, candidate: SourceCandidate) -> dict:
        """把运行时来源候选转换为可安全持久化的字段。"""

        torrent = candidate.torrent

        def read(name: str, default: Any = None) -> Any:
            """兼容字典与对象形式读取来源种子字段。"""

            if isinstance(torrent, dict):
                return torrent.get(name, default)
            return getattr(torrent, name, default)

        return {
            "candidate_id": self._candidate_id(candidate),
            "iyuu_sid": candidate.match.sid,
            "site_id": candidate.site_id,
            "site_name": candidate.site_name,
            "title": read("title"),
            "page_url": safe_page_url(read("page_url")),
            "torrent_id": candidate.match.torrent_id,
            "expected_hash": candidate.match.info_hash,
            "seeders": candidate.seeders,
            "leechers": read("peers"),
            "grabs": read("grabs"),
            "size": read("size"),
            "download_factor": candidate.download_factor,
            "promotion": promotion_kind(candidate.download_factor),
            "priority": candidate.priority,
            "metadata_status": candidate.metadata_status,
            "metadata_error": candidate.metadata_error,
            "lookup_method": candidate.lookup_method,
        }

    @staticmethod
    def _target_candidate_id(job: dict) -> str:
        """原种候选使用稳定标识，兼容尚未补齐种子 ID 的旧任务。"""

        return f"target:{job.get('target_site_id')}:{job['target_hash']}"

    @classmethod
    def _display_candidates(cls, job: dict) -> List[dict]:
        """兼容旧版仅保存探测结果的来源，展示只读候选而不修改任务数据。"""

        candidates = [dict(candidate) for candidate in job.get("candidates") or []]
        identities = {
            (str(candidate.get("site_id")), str(candidate.get("torrent_id") or extract_torrent_id(candidate.get("page_url"))))
            for candidate in candidates
        }
        for probe in job.get("probes") or []:
            torrent_id = probe.get("torrent_id") or extract_torrent_id(probe.get("page_url"))
            identity = (str(probe.get("site_id")), str(torrent_id))
            if not torrent_id or probe.get("site_id") is None or identity in identities:
                continue
            identities.add(identity)
            candidates.append({
                "candidate_id": f"probe:{identity[0]}:{identity[1]}",
                **{key: probe.get(key) for key in ("site_id", "site_name", "title", "seeders", "promotion")},
                "torrent_id": str(torrent_id),
                "page_url": safe_page_url(probe.get("page_url")),
                "eligible": False,
                "metadata_status": probe.get("metadata_status") or ("ready" if probe.get("matched") else "unavailable"),
                "exclusion_reason": "旧记录未取得详情，请重新匹配按 ID 查询" if not probe.get("matched") else (
                    job.get("reason") or "旧记录未保存下载资格，请重新匹配确认"
                ),
            })
        return candidates

    @classmethod
    def _job_view(cls, job: dict) -> dict:
        """返回不包含站点凭据和下载地址的任务副本。"""

        allowed = {
            "target_hash",
            "target_site_id",
            "target_site_name",
            "target_torrent_id",
            "target_page_url",
            "target_seeders",
            "target_peers",
            "target_grabs",
            "target_size",
            "target_download_factor",
            "target_stats_updated_at",
            "target_stats_checked_at",
            "target_stats_error",
            "target_promotion_updated_at",
            "title",
            "state",
            "created_at",
            "updated_at",
            "rss_current",
            "rss_last_seen_at",
            "rss_archived_at",
            "source_hash",
            "source_site_id",
            "source_site_name",
            "source_seeders",
            "promotion",
            "reason",
            "retry_count",
            "next_retry_at",
            "probes",
            "candidates",
            "selected_candidate_id",
        }
        view = {key: value for key, value in job.items() if key in allowed}
        view["candidates"] = cls._display_candidates(job)
        if job.get("target_site_id"):
            view["target_candidate"] = {
                "candidate_id": cls._target_candidate_id(job),
                "is_target": True,
                "selectable": job.get("state") in cls.TARGET_SELECTABLE_STATES,
                "site_id": job["target_site_id"],
                "site_name": job.get("target_site_name") or "保种站点",
                "title": job.get("title"),
                "page_url": safe_page_url(job.get("target_page_url")),
                "seeders": job.get("target_seeders"),
                "leechers": job.get("target_peers"),
                "grabs": job.get("target_grabs"),
                "size": job.get("target_size"),
                "download_factor": job.get("target_download_factor"),
                "promotion": promotion_kind(job.get("target_download_factor")),
                "promotion_updated_at": job.get("target_promotion_updated_at") or (
                    job.get("target_stats_updated_at")
                    if promotion_kind(job.get("target_download_factor")) != UNKNOWN else None
                ),
                "promotion_note": job.get("target_stats_error") or (
                    ("待补查原站促销" if job.get("target_torrent_id") else "旧记录缺少原站种子 ID，等待 RSS 再次发现")
                    if promotion_kind(job.get("target_download_factor")) == UNKNOWN else None
                ),
            }
        return view

    @staticmethod
    def _frontend_options() -> dict:
        """返回配置页可选择的私有站点和 qBittorrent 下载器。"""

        sites = [
            {"title": item.get("name"), "value": item.get("id")}
            for item in SitesHelper().get_indexers()
            if not item.get("public")
        ]
        downloaders = [
            {"title": name, "value": name}
            for name, conf in DownloaderHelper().get_configs().items()
            if conf.type == "qbittorrent"
        ]
        return {"sites": sites, "downloaders": downloaders}

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """Vue 配置组件只需要接收当前配置模型。"""

        return [], self._current_config()

    def get_page(self) -> List[dict]:
        """Vue 详情组件通过插件 API 获取页面数据。"""

        return []

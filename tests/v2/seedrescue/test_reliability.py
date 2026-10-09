import copy
import threading
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from . import test_plugin as fixtures

DownloaderHelper = fixtures.DownloaderHelper
FakeIyuu = fixtures.FakeIyuu
plugin_module = fixtures.plugin_module


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.helper = fixtures.PluginWorkflowTests()
        self.addCleanup(self.helper.doCleanups)

    def scan_plugin(self):
        plugin = self.helper.rss_setup()
        # 像实际存储一样复制数据，避免引用共享掩盖未保存的问题。
        plugin.get_data = lambda key: copy.deepcopy(plugin._data.get(key))
        plugin.save_data = lambda key, value: plugin._data.__setitem__(key, copy.deepcopy(value))
        plugin._valid_config = lambda log_error=False: True
        plugin._reconcile_jobs = lambda jobs: None
        plugin._refresh_target_jobs = lambda jobs, site: None
        site = SimpleNamespace(name='target', domain='target.example', proxy=False, timeout=1, ua=None)
        mock = patch.object(plugin_module, 'SiteOper', lambda: SimpleNamespace(get=lambda _: site))
        mock.start()
        self.addCleanup(mock.stop)
        return plugin

    def test_background_scan_returns_without_waiting_and_rejects_duplicate_start(self):
        plugin = self.scan_plugin()
        entered, release = threading.Event(), threading.Event()

        def parse(*args, **kwargs):
            entered.set()
            release.wait(2)
            return []

        with patch.object(plugin_module, 'RssHelper', lambda: SimpleNamespace(parse=parse)):
            started = time.monotonic()
            response = plugin.scan_now()
            self.assertTrue(response.success)
            self.assertLess(time.monotonic() - started, 0.5)
            worker = plugin._scan_thread
            try:
                self.assertTrue(entered.wait(1))
                data = plugin.get_status().data
                self.assertEqual(data['scan_status']['state'], 'running')
                self.assertEqual(data['scan_status']['stage'], 'rss')
                self.assertTrue(data['busy'])
                self.assertFalse(plugin.scan_now().success)
                self.assertFalse(plugin.ignore_job('a' * 40).success)
            finally:
                release.set()
                worker.join(2)
        self.assertFalse(plugin._lock.locked())
        self.assertEqual(plugin.get_status().data['scan_status']['state'], 'success')

    def test_scan_exception_is_failed_and_does_not_expose_exception_secrets(self):
        plugin = self.scan_plugin()
        plugin._reconcile_jobs = lambda jobs: (_ for _ in ()).throw(RuntimeError('passkey=secret'))
        plugin.scan()
        status = plugin.get_status().data['scan_status']
        self.assertEqual(status['state'], 'failed')
        self.assertNotIn('secret', str(status))
        self.assertIsNotNone(status['finished_at'])
        self.assertFalse(plugin._lock.locked())

    def test_all_feed_failures_report_failed_partial_failure_reports_partial(self):
        for partial in (False, True):
            plugin = self.scan_plugin()
            plugin._rss_urls = ['https://target/rss1', 'https://target/rss2']
            responses = iter([False, [] if partial else False])
            with patch.object(plugin_module, 'RssHelper', lambda: SimpleNamespace(parse=lambda *args, **kwargs: next(responses))):
                plugin.scan()
            self.assertEqual(plugin._get_scan_status()['state'], 'partial' if partial else 'failed')

    def test_stale_running_scan_is_interrupted_on_initialization(self):
        plugin = plugin_module.SeedRescue()
        plugin._data[plugin.SCAN_STATUS_KEY] = {'state': 'running', 'stage': 'matching'}
        plugin.init_plugin({})
        self.assertEqual(plugin.get_data(plugin.SCAN_STATUS_KEY)['state'], 'interrupted')

    def test_stop_during_rss_does_not_overwrite_saved_snapshot(self):
        plugin = self.scan_plugin()
        old = {'previous': {'last_success_at': '2026-01-01'}}
        plugin.save_data(plugin.RSS_SNAPSHOTS_KEY, old)

        def parse(*args, **kwargs):
            plugin.stop_service()
            return []

        with patch.object(plugin_module, 'RssHelper', lambda: SimpleNamespace(parse=parse)):
            plugin.scan()
        self.assertEqual(plugin.get_data(plugin.RSS_SNAPSHOTS_KEY), old)
        self.assertEqual(plugin._get_scan_status()['state'], 'interrupted')
        self.assertFalse(plugin._lock.locked())

    def test_persistence_failure_is_visible_and_releases_lock(self):
        plugin = self.scan_plugin()
        plugin._save_jobs = lambda jobs: (_ for _ in ()).throw(OSError('private path'))
        plugin.scan()
        status = plugin._get_scan_status()
        self.assertEqual(status['state'], 'failed')
        self.assertIn('保存失败', status['message'])
        self.assertNotIn('private', str(status))
        self.assertIsNotNone(status['finished_at'])
        self.assertFalse(plugin._lock.locked())

    def test_matching_recovers_and_retry_backoff_has_a_limit(self):
        plugin = self.scan_plugin()
        job = self.helper.rss_job(1, state='MATCHING')
        plugin._scan_jobs = {job['target_hash']: job}
        plugin._iyuu = FakeIyuu({}, 'not found')
        plugin._resume_waiting_jobs(plugin._scan_jobs)
        self.assertEqual(plugin.get_data(plugin.JOBS_KEY)[job['target_hash']]['state'], 'SKIPPED_NO_IYUU_MATCH')
        for attempt in range(1, plugin.MAX_AUTO_RETRIES + 1):
            plugin._defer_retry(job, 'network failed')
            self.assertEqual(job['retry_count'], attempt)
            calls = []
            with patch.object(plugin, '_find_and_download', lambda job: calls.append(job)):
                plugin._resume_waiting_jobs(plugin._scan_jobs)
                self.assertEqual(calls, [])
        self.assertEqual(job['state'], 'FAILED_MATCHING')
        self.assertIsNone(job['next_retry_at'])

    def test_source_failure_is_retryable_not_no_match_and_does_not_discard_good_candidates(self):
        plugin = self.helper.rss_setup()
        plugin._source_site_ids = [7, 8]
        matches = [plugin_module.IyuuMatch(7, '11', 'b' * 40), plugin_module.IyuuMatch(8, '12', 'c' * 40)]
        plugin._iyuu = SimpleNamespace(get_torrent_url=lambda sid: (str(sid), None))
        candidate = plugin_module.SourceCandidate(matches[1], 8, 'good', 5, 0, 0)

        def probe(domain, entries, title, priority):
            if domain == '7':
                raise TimeoutError('secret')
            return [(1, candidate, {'site_id': 8, 'matched': True})]

        plugin._probe_domain = probe
        with patch.object(plugin_module, 'StringUtils', SimpleNamespace(get_url_domain=lambda url: url)), \
                patch.object(plugin_module, 'SitesHelper', lambda: SimpleNamespace(get_indexer=lambda domain: {'id': int(domain), 'name': domain})):
            candidates, probes = plugin._probe_sources(matches, 'title')
        self.assertEqual(candidates[1], candidate)
        self.assertEqual(candidates[0].metadata_status, 'unavailable')
        self.assertTrue(probes[0]['error'])
        self.assertNotIn('secret', str(probes))
        job = self.helper.rss_job(1)
        plugin._apply_candidates(job, candidates, probes)
        self.assertEqual(job['state'], 'AWAITING_SELECTION')
        plugin._apply_candidates(job, [], probes[:1])
        self.assertEqual(job['state'], 'WAITING_SOURCE_RETRY')

    def test_paid_download_needs_exact_server_side_confirmation(self):
        plugin, job, calls = self.helper.target_download_setup()
        candidate_id = plugin._target_candidate_id(job)
        for fields in ({}, {'confirmed_download_factor': 0.5}, {'confirm_unknown': True}):
            response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(candidate_id=candidate_id, **fields))
            self.assertFalse(response.success)
            self.assertTrue(response.data['confirmation_required'])
            self.assertEqual(response.data['download_factor'], 1)
            self.assertEqual(calls, [])
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(candidate_id=candidate_id, confirmed_download_factor=1))
        self.assertTrue(response.success)
        self.assertEqual(len(calls), 1)

    def test_unknown_promotion_requires_separate_confirmation(self):
        plugin, job, calls = self.helper.target_download_setup()
        candidate, _ = plugin._target_source(job)
        plugin._target_source = lambda job: (replace(candidate, download_factor=None), '')
        candidate_id = plugin._target_candidate_id(job)
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(candidate_id=candidate_id, confirmed_download_factor=1))
        self.assertTrue(response.data['confirmation_required'])
        self.assertEqual(calls, [])
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(candidate_id=candidate_id, confirm_unknown=True))
        self.assertTrue(response.success)
        self.assertEqual(len(calls), 1)

    def test_risk_reminder_defaults_on_and_only_explicit_false_disables_it(self):
        plugin = plugin_module.SeedRescue()
        for value in (None, True, '', 'false', 0):
            plugin.init_plugin({'confirm_download_risk': value})
            self.assertTrue(plugin._current_config()['confirm_download_risk'])
        plugin.init_plugin({'confirm_download_risk': False})
        self.assertFalse(plugin._current_config()['confirm_download_risk'])

    def test_skip_future_flag_alone_or_stale_confirmation_does_not_disable_reminder(self):
        plugin, job, calls = self.helper.target_download_setup()
        for fields in ({}, {'confirmed_download_factor': 0.5}, {'confirm_unknown': True}):
            response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
                candidate_id=plugin._target_candidate_id(job), skip_future_risk_confirmation=True, **fields))
            self.assertTrue(response.data['confirmation_required'])
            self.assertTrue(plugin._confirm_download_risk)
            self.assertFalse(hasattr(plugin, 'saved_config'))
        self.assertEqual(calls, [])

    def test_remember_confirmed_choice_persists_and_can_be_reenabled(self):
        plugin, job, calls = self.helper.target_download_setup()
        original_config = plugin._current_config()
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1,
            skip_future_risk_confirmation=True))
        self.assertTrue(response.success)
        self.assertEqual(plugin.saved_config, {**original_config, 'confirm_download_risk': False})
        plugin.init_plugin(copy.deepcopy(plugin.saved_config))
        self.assertFalse(plugin._confirm_download_risk)
        job['state'] = 'AWAITING_SELECTION'
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job)))
        self.assertTrue(response.success)
        self.assertEqual(len(calls), 2)
        plugin.init_plugin({**plugin.saved_config, 'confirm_download_risk': True})
        job['state'] = 'AWAITING_SELECTION'
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job)))
        self.assertTrue(response.data['confirmation_required'])
        self.assertEqual(len(calls), 2)

    def test_unknown_remembered_and_unchecked_confirmation_not_remembered(self):
        plugin, job, calls = self.helper.target_download_setup()
        candidate, _ = plugin._target_source(job)
        plugin._target_source = lambda job: (replace(candidate, download_factor=None), '')
        candidate_id = plugin._target_candidate_id(job)
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
            candidate_id=candidate_id, confirm_unknown=True))
        self.assertTrue(response.success)
        self.assertTrue(plugin._confirm_download_risk)
        self.assertFalse(hasattr(plugin, 'saved_config'))
        job['state'] = 'AWAITING_SELECTION'
        response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
            candidate_id=candidate_id, confirm_unknown=True, skip_future_risk_confirmation=True))
        self.assertTrue(response.success)
        self.assertFalse(plugin.saved_config['confirm_download_risk'])
        job['state'] = 'AWAITING_SELECTION'
        self.assertTrue(plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
            candidate_id=candidate_id)).success)
        self.assertEqual(len(calls), 3)

    def test_failed_preference_save_does_not_disable_reminder_or_add_torrent(self):
        plugin, job, calls = self.helper.target_download_setup()
        plugin.update_config = lambda config: (_ for _ in ()).throw(OSError('save failed'))
        with self.assertRaises(OSError):
            plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
                candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1,
                skip_future_risk_confirmation=True))
        self.assertTrue(plugin._confirm_download_risk)
        self.assertEqual(calls, [])
        self.assertFalse(plugin._lock.locked())

    def test_disabled_reminder_still_checks_hash_and_capacity(self):
        plugin, job, calls = self.helper.target_download_setup()
        plugin.init_plugin({**plugin._current_config(), 'confirm_download_risk': False})
        payload = plugin_module.CandidateSelectionPayload(candidate_id=plugin._target_candidate_id(job))
        plugin._downloading_count = lambda: plugin._max_download_count
        self.assertIn('上限', plugin.download_candidate(job['target_hash'], payload).message)
        plugin._downloading_count = lambda: 0
        with patch.object(plugin_module, 'TorrentHelper', lambda: SimpleNamespace(
                download_torrent=lambda **kwargs: (None, b'd4:infod6:lengthi2e4:name1:xee', '', [], ''))):
            response = plugin.download_candidate(job['target_hash'], payload)
        self.assertFalse(response.success)
        self.assertIn('Hash', response.message)
        self.assertEqual(calls, [])

    def test_uncertain_add_is_persisted_and_never_resubmitted(self):
        plugin, job, calls = self.helper.target_download_setup()
        attempts = []

        def uncertain_add(**kwargs):
            stored = plugin.get_data(plugin.JOBS_KEY)[job['target_hash']]
            self.assertEqual(stored['state'], 'SOURCE_SUBMITTING')
            self.assertEqual(stored['source_hash'], job['target_hash'])
            attempts.append(True)
            raise TimeoutError('possibly accepted')

        with patch.object(DownloaderHelper, 'service', SimpleNamespace(instance=SimpleNamespace(add_torrent=uncertain_add))):
            payload = plugin_module.CandidateSelectionPayload(candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1)
            response = plugin.download_candidate(job['target_hash'], payload)
            self.assertFalse(response.success)
            self.assertEqual(job['state'], 'SOURCE_SUBMITTING')
            self.assertFalse(plugin.download_candidate(job['target_hash'], payload).success)
            plugin._resume_waiting_jobs({job['target_hash']: job})
        self.assertEqual(len(attempts), 1)
        plugin._get_torrent = lambda _: {'progress': 0.3, 'state': 'downloading'}
        plugin._reconcile_jobs({job['target_hash']: job})
        self.assertEqual(job['state'], 'TARGET_DOWNLOADING')

    def test_host_false_response_is_also_uncertain_and_not_resubmitted(self):
        plugin, job, _ = self.helper.target_download_setup()
        attempts = []
        service = SimpleNamespace(instance=SimpleNamespace(
            add_torrent=lambda **kwargs: attempts.append(True) or (False, [])))
        payload = plugin_module.CandidateSelectionPayload(
            candidate_id=plugin._target_candidate_id(job), confirmed_download_factor=1)
        with patch.object(DownloaderHelper, 'service', service):
            self.assertFalse(plugin.download_candidate(job['target_hash'], payload).success)
            self.assertEqual(job['state'], 'SOURCE_SUBMITTING')
            self.assertFalse(plugin.download_candidate(job['target_hash'], payload).success)
        self.assertEqual(attempts, [True])

    def test_rss_fallback_does_not_trust_old_free_promotion(self):
        plugin, job, calls = self.helper.target_download_setup()
        job['target_download_factor'] = 0
        plugin._refresh_target_job = lambda *args: None
        item = {'enclosure': 'https://target.example/download.php?id=88', 'title': job['title']}
        with patch.object(plugin_module, 'RssHelper', lambda: SimpleNamespace(parse=lambda *args, **kwargs: [item])):
            response = plugin.download_candidate(job['target_hash'], plugin_module.CandidateSelectionPayload(
                candidate_id=plugin._target_candidate_id(job)))
        self.assertFalse(response.success)
        self.assertEqual(response.data['promotion'], 'unknown')
        self.assertTrue(response.data['confirmation_required'])
        self.assertEqual(calls, [])

    def test_completed_target_is_rechecked_and_does_not_repeat_success_notifications(self):
        plugin = self.helper.rss_setup()
        plugin._notify = True
        job = self.helper.rss_job(1, state='TARGET_DOWNLOADING')
        plugin._get_torrent = lambda _: {'progress': 1, 'state': 'uploading'}
        for _ in range(2):
            plugin._reconcile_jobs({job['target_hash']: job})
        self.assertEqual(len(plugin.messages), 1)
        plugin._get_torrent = lambda _: {'progress': 1, 'state': 'stoppedUP'}
        plugin._reconcile_jobs({job['target_hash']: job})
        self.assertEqual(job['state'], 'TARGET_PAUSED')

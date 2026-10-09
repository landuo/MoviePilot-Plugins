import hashlib
import importlib.util
import sys
import unittest
from pathlib import Path


CORE_PATH = Path(__file__).parents[3] / "plugins.v2" / "seedrescue" / "core.py"
SPEC = importlib.util.spec_from_file_location("seedrescue_core", CORE_PATH)
core = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


def torrent_bytes(name: bytes = b"example.mkv", length: int = 100) -> bytes:
    info = b"d6:lengthi" + str(length).encode() + b"e4:name" + str(len(name)).encode() + b":" + name + b"e"
    return b"d8:announce14:https://t.test4:info" + info + b"e"


class InfoHashTests(unittest.TestCase):
    def test_hashes_original_info_slice(self):
        content = torrent_bytes()
        info = b"d6:lengthi100e4:name11:example.mkve"
        self.assertEqual(core.info_hash_from_torrent(content), hashlib.sha1(info).hexdigest())

    def test_rejects_missing_info(self):
        with self.assertRaises(core.TorrentFormatError):
            core.info_hash_from_torrent(b"d3:fooi1ee")

    def test_rejects_truncated_bencode(self):
        with self.assertRaises(core.TorrentFormatError):
            core.info_hash_from_torrent(b"d4:infod4:name20:short")


class IyuuTests(unittest.TestCase):
    def test_extracts_and_deduplicates_matches(self):
        target = "a" * 40
        source = "B" * 40
        payload = {target.upper(): {"torrent": [
            {"sid": 3, "torrent_id": 42, "info_hash": source},
            {"sid": 3, "torrent_id": 42, "info_hash": source},
            {"sid": None, "torrent_id": 9, "info_hash": "c" * 40},
        ]}}
        self.assertEqual(
            core.iyuu_matches_for_hash(payload, target),
            [core.IyuuMatch(3, "42", source.lower())],
        )

    def test_supports_single_torrent_object(self):
        target = "a" * 40
        payload = {target: {"torrent": {"sid": "8", "torrent_id": "9", "info_hash": "b" * 40}}}
        self.assertEqual(len(core.iyuu_matches_for_hash(payload, target)), 1)

    def test_preserves_same_info_hash_from_different_sites(self):
        target = "a" * 40
        source = "b" * 40
        payload = {target: {"torrent": [
            {"sid": 3, "torrent_id": 42, "info_hash": source},
            {"sid": 4, "torrent_id": 99, "info_hash": source},
        ]}}

        self.assertEqual(len(core.iyuu_matches_for_hash(payload, target)), 2)


class SelectionTests(unittest.TestCase):
    @staticmethod
    def candidate(seed_hash, site_id, seeders, factor, priority):
        return core.SourceCandidate(
            match=core.IyuuMatch(str(site_id), str(site_id), seed_hash * 40),
            site_id=site_id,
            site_name=f"site-{site_id}",
            seeders=seeders,
            download_factor=factor,
            priority=priority,
        )

    def test_below_minimum_and_unknown_are_skipped(self):
        rows = [
            self.candidate("a", 1, 9, 0, 0),
            self.candidate("b", 2, None, 0, 1),
        ]
        self.assertEqual(core.ranked_sources(rows, 10, [core.FREE, core.NON_FREE]), [])

    def test_free_only(self):
        rows = [
            self.candidate("a", 1, 20, 1, 0),
            self.candidate("b", 2, 10, 0, 1),
        ]
        selected = core.ranked_sources(rows, 10, [core.FREE])
        self.assertEqual([item.site_id for item in selected], [2])

    def test_unset_minimum_keeps_zero_and_unknown_counts_but_still_filters_promotions(self):
        rows = [
            self.candidate("a", 1, 0, 0, 0),
            self.candidate("b", 2, None, 0, 1),
            self.candidate("c", 3, 5, 1, 2),
            self.candidate("d", 4, 100, None, 3),
        ]
        self.assertEqual([item.site_id for item in core.ranked_sources(rows, None, [core.FREE])], [1, 2])
        self.assertEqual([item.site_id for item in core.ranked_sources(rows, None, [core.FREE, core.NON_FREE])], [3, 1, 2])

    def test_non_free_only(self):
        rows = [
            self.candidate("a", 1, 20, 0, 0),
            self.candidate("b", 2, 10, 0.5, 1),
        ]
        selected = core.ranked_sources(rows, 10, [core.NON_FREE])
        self.assertEqual([item.site_id for item in selected], [2])

    def test_both_prefers_more_seeders_then_promotion(self):
        rows = [
            self.candidate("a", 1, 100, 1, 0),
            self.candidate("b", 2, 10, 0, 1),
            self.candidate("c", 3, 99, 0, 2),
        ]
        selected = core.ranked_sources(rows, 10, [core.FREE, core.NON_FREE])
        self.assertEqual([item.site_id for item in selected], [1, 3, 2])

    def test_discount_is_non_free(self):
        self.assertEqual(core.promotion_kind(0), core.FREE)
        self.assertEqual(core.promotion_kind(0.3), core.NON_FREE)
        self.assertEqual(core.promotion_kind(1), core.NON_FREE)
        self.assertEqual(core.promotion_kind(None), core.UNKNOWN)

    def test_single_promotion_string_is_normalized_as_one_choice(self):
        self.assertEqual(core.normalize_promotions(core.FREE), {core.FREE})


class HelpersTests(unittest.TestCase):
    def test_extracts_common_torrent_ids(self):
        self.assertEqual(core.extract_torrent_id("https://a/details.php?id=123&hit=1"), "123")
        self.assertEqual(core.extract_torrent_id("https://a/torrents/456"), "456")
        self.assertEqual(core.extract_torrent_id("https://a/view?torrentid=789"), "789")

    def test_safe_page_url_removes_site_secrets(self):
        url = "https://tracker.example/details.php?id=42&hit=1&passkey=secret&token=hidden#top"
        result = core.safe_page_url(url)
        self.assertEqual(result, "https://tracker.example/details.php?id=42&hit=1")
        self.assertIsNone(core.safe_page_url("javascript:alert(1)"))
        self.assertIsNone(core.safe_page_url("https://user:password@tracker.example/details.php?id=42"))

    def test_feed_key_does_not_contain_secret(self):
        secret = "https://a/rss?passkey=very-secret"
        result = core.feed_key(secret, "", "")
        self.assertNotIn("very-secret", result)
        self.assertEqual(len(result), 64)

    def test_search_keywords_include_media_name_fallback(self):
        self.assertEqual(
            core.search_keywords("Movie.Name.2024.1080p.BluRay"),
            ["Movie Name 2024", "Movie Name", "Movie.Name.2024.1080p.BluRay"],
        )
        self.assertEqual(
            core.search_keywords("Show.Name.S02E03.2160p"),
            ["Show Name S02", "Show Name", "Show.Name.S02E03.2160p"],
        )

    def test_complete_supports_fraction_and_percent(self):
        self.assertTrue(core.torrent_is_complete({"progress": 1.0}))
        self.assertTrue(core.torrent_is_complete({"progress": 100}))
        self.assertFalse(core.torrent_is_complete({"progress": 0.5, "state": "downloading"}))

    def test_completion_is_strict_and_does_not_bypass_checks_or_missing_files(self):
        for progress in (0.999, 0.9995, 0.999999, 99.95, 99.999, 101, float('nan'), float('inf')):
            self.assertFalse(core.torrent_is_complete({"progress": progress, "state": "uploading"}))
        for state in ("checkingUP", "checkingDL", "checkingResumeData", "error", "missingFiles"):
            self.assertFalse(core.torrent_is_complete({"progress": 1, "state": state}))
        self.assertFalse(core.torrent_is_complete({"progress": 1, "amount_left": 1, "state": "uploading"}))

    def test_target_status_separates_complete_paused_and_actual_seeding(self):
        for state, expected in [
            ('uploading', 'TARGET_SEEDING'), ('stalledUP', 'TARGET_SEEDING'),
            ('forcedUP', 'TARGET_SEEDING'), ('pausedUP', 'TARGET_PAUSED'),
            ('stoppedUP', 'TARGET_PAUSED'), ('queuedUP', 'TARGET_COMPLETE'),
            ('checkingUP', 'TARGET_RECHECKING'), ('error', 'TARGET_ERROR'),
            ('missingFiles', 'TARGET_ERROR'), ('', 'TARGET_COMPLETE'),
        ]:
            self.assertEqual(core.target_torrent_status({'progress': 1, 'state': state})[0], expected)
        self.assertEqual(core.target_torrent_status({'progress': 0.9995, 'state': 'downloading'})[0], 'TARGET_DOWNLOADING')


if __name__ == "__main__":
    unittest.main()

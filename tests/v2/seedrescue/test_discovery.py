import copy
from types import SimpleNamespace

import pytest

from . import test_plugin as fixtures

host = fixtures.plugin_module


@pytest.fixture
def plugin():
    helper = fixtures.PluginWorkflowTests()
    value = helper.rss_setup()
    value._minimum_seeders = 5
    value._selection_mode = "manual"
    yield value
    helper.doCleanups()


def row(torrent_id, seeders=7):
    return SimpleNamespace(page_url=f"https://source/details.php?id={torrent_id}",
                           enclosure=None, title="House of the Dragon S01",
                           seeders=seeders, downloadvolumefactor=0)


def probe(plugin, monkeypatch, browse, ids=("42",), title="House of the Dragon S01 2160p H265-HHWEB"):
    monkeypatch.setattr(host, "TorrentsChain", lambda: SimpleNamespace(browse=browse))
    entries = [(i, host.IyuuMatch(3, tid, str(i + 1) * 40), {"id": 2, "name": "source"})
               for i, tid in enumerate(ids)]
    return plugin._probe_domain("source", entries, title, {2: 0})


def test_season_keyword_precedes_generic_and_full_release():
    assert host.search_keywords("The.World.from.Above.2010.S05.1080p")[0] == "The World from Above S05"
    assert host.search_keywords("Show.Name.S02E03.2160p")[0] == "Show Name S02"
    assert host.search_keywords("Movie.Name.2024.1080p")[:2] == ["Movie Name 2024", "Movie Name"]


def test_specific_keyword_can_stop_after_one_request(plugin, monkeypatch):
    calls = []

    def browse(domain, keyword, page=0):
        calls.append((keyword, page))
        return [row("42")] if keyword == "House of the Dragon S01" else []

    result = probe(plugin, monkeypatch, browse)
    assert result[0][1].match.torrent_id == "42"
    assert calls == [("House of the Dragon S01", 0)]


def test_third_page_match_is_kept_but_similar_title_wrong_id_is_not(plugin, monkeypatch):
    calls = []

    def browse(domain, keyword, page=0):
        calls.append((keyword, page))
        return [row("42" if page == 2 else str(100 + page))]

    result = probe(plugin, monkeypatch, browse)
    assert result[0][1].match.torrent_id == "42"
    assert result[0][2]["searches"] == len(calls)
    assert any(page == 2 for _, page in calls)
    assert len(calls) <= plugin.MAX_SOURCE_SEARCHES


@pytest.mark.parametrize("response", [[], [row("99")]])
def test_empty_or_repeating_pages_stop_and_do_not_match_by_title(plugin, monkeypatch, response):
    calls = []

    def browse(domain, keyword, page=0):
        calls.append((keyword, page))
        return response

    result = probe(plugin, monkeypatch, browse)
    assert result[0][1].metadata_status == "unavailable"
    assert result[0][1].match.torrent_id == "42"
    assert result[0][1].seeders is None
    assert len(calls) <= 5
    assert max(page for _, page in calls) <= (1 if response else 0)


def test_page_and_request_budgets_are_bounded_and_reported(plugin, monkeypatch):
    calls = []

    def browse(domain, keyword, page=0):
        calls.append((keyword, page))
        return [row(str(100 + page))]

    result = probe(plugin, monkeypatch, browse)
    assert len(calls) <= plugin.MAX_SOURCE_SEARCHES
    assert max(page for _, page in calls) == plugin.MAX_SOURCE_PAGES - 1
    assert result[0][2]["search_limited"]


def test_later_request_failure_preserves_already_matched_source(plugin, monkeypatch):
    calls = []

    def browse(domain, keyword, page=0):
        calls.append((keyword, page))
        if len(calls) > 1:
            raise RuntimeError("passkey=private")
        return [row("42")]

    result = probe(plugin, monkeypatch, browse, ids=("42", "43"))
    assert result[0][1] is not None
    assert result[1][1].metadata_status == "unavailable"
    assert result[1][2]["error"]
    assert "private" not in str(result)


def test_excluded_sources_are_visible_but_do_not_count_for_hybrid_download(plugin):
    healthy = host.SourceCandidate(host.IyuuMatch(3, "42", "b" * 40), 2, "healthy", 7, 0, 0, row("42"))
    low = host.SourceCandidate(host.IyuuMatch(4, "43", "c" * 40), 3, "low", 2, 0, 1, row("43", 2))
    job = {"target_hash": "a" * 40, "title": "show"}
    plugin._apply_candidates(job, [low, healthy], [])
    assert job["state"] == "AWAITING_SELECTION"
    assert [c["eligible"] for c in job["candidates"]] == [True, False]
    assert "5" in job["candidates"][1]["exclusion_reason"]
    plugin._selection_mode = "hybrid"
    plugin._at_download_capacity = lambda: False
    submitted = []
    plugin._start_source = lambda candidate, job: (submitted.append(candidate) or True, "")
    plugin._apply_candidates(job, [low, healthy], [])
    assert submitted == [healthy]


def test_filtered_candidate_cannot_be_submitted_by_forging_selection(plugin):
    candidate = host.SourceCandidate(host.IyuuMatch(3, "42", "b" * 40), 2, "low", 2, 0, 0, row("42", 2))
    job = {"target_hash": "a" * 40, "title": "show", "state": "AWAITING_SELECTION",
           "candidates": [{**plugin._candidate_record(candidate), "eligible": False}]}
    plugin.save_data(plugin.JOBS_KEY, {job["target_hash"]: job})
    plugin._probe_sources = lambda *args: pytest.fail("已排除候选不得提交")
    response = plugin.download_candidate(job["target_hash"], host.CandidateSelectionPayload(
        candidate_id=plugin._candidate_id(candidate)))
    assert not response.success


def test_old_matched_probes_are_visible_and_filterable_without_writing(plugin):
    job = {"target_hash": "a" * 40, "rss_current": True, "state": "SKIPPED_NO_HEALTHY_SOURCE",
           "candidates": [], "probes": [{"site_id": 2, "site_name": "source", "matched": True,
           "page_url": "https://source/details.php?id=42&passkey=secret", "seeders": 2, "promotion": "free"}]}
    snapshot = copy.deepcopy(job)
    plugin.save_data(plugin.JOBS_KEY, {job["target_hash"]: job})
    data = plugin.get_status(source_site_id=2, source_promotion="free").data
    assert data["pagination"]["total"] == 1
    candidate = data["jobs"][0]["candidates"][0]
    assert candidate["eligible"] is False
    assert candidate["seeders"] == 2
    assert "secret" not in candidate["page_url"]
    assert job == snapshot
    job["candidates"] = [{"site_id": 2, "torrent_id": "42", "candidate_id": "saved", "eligible": True}]
    assert len(plugin._job_view(job)["candidates"]) == 1


def test_old_unmatched_iyuu_probe_is_shown_as_pending_without_rewriting(plugin):
    job = {"target_hash": "a" * 40, "rss_current": False, "candidates": [],
           "probes": [{"site_id": 2, "site_name": "source", "torrent_id": "42", "matched": False}]}
    snapshot = copy.deepcopy(job)
    plugin.save_data(plugin.JOBS_KEY, {job["target_hash"]: job})
    data = plugin.get_status(view="history", source_site_id=2, source_promotion="unknown").data
    assert data["pagination"]["total"] == 1
    candidate = data["jobs"][0]["candidates"][0]
    assert candidate["metadata_status"] == "unavailable" and candidate["eligible"] is False
    assert job == snapshot

import base64
import json
from types import SimpleNamespace

import pytest

from .test_discovery import plugin, host

detail = __import__(host.__name__ + '.detail', fromlist=['detail'])


@pytest.fixture(autouse=True)
def flow_control(monkeypatch):
    monkeypatch.setattr(host, 'SitesHelper', lambda: SimpleNamespace(check=lambda domain: (False, '')))


def mteam(discount='PERCENT_50', **status):
    return {'code': '0', 'data': {'id': '42', 'name': 'Show S01', 'size': '1024',
            'status': {'seeders': '8', 'leechers': '0', 'timesCompleted': '25',
                       'discount': discount, **status}}}


def site(**kwargs):
    return {'id': 2, 'name': 'source', 'domain': 'https://kp.m-team.cc/',
            'apikey': 'SECRET', **kwargs}


def requester(payload=None, text='', code=200):
    response = SimpleNamespace(status_code=code, text=text, json=lambda: payload)
    calls = []

    def request(**kwargs):
        def get(url, **params):
            calls.append((url, kwargs, params))
            return response
        return SimpleNamespace(get_res=get, post_res=get)
    return request, calls


def test_mteam_exact_id_complete_stats_and_indirect_download_without_requesting_token():
    request, calls = requester(mteam())
    result = detail.fetch_detail(site(), '42', request)
    assert result.status == 'ready'
    assert result.torrent['seeders'] == 8
    assert result.torrent['peers'] == 0
    assert result.torrent['grabs'] == 25
    assert result.torrent['downloadvolumefactor'] == 0.5
    assert len(calls) == 1 and calls[0][0].endswith('/api/torrent/detail')
    assert calls[0][2]['data'] == {'id': '42'}
    assert calls[0][2]['allow_redirects'] is False
    enclosure = result.torrent['enclosure']
    data = json.loads(base64.b64decode(enclosure[1:enclosure.index(']')]))
    assert data['params'] == {'id': '42'} and data['header']['x-api-key'] == 'SECRET'


@pytest.mark.parametrize('status,factor', [({}, 0.5), ({'promotionRule': {'discount': 'FREE'}}, 0),
    ({'promotionRule': {'discount': 'NORMAL'}}, 1),
    ({'mallSingleFree': {'status': 'ONGOING'}}, 0), ({'discount': 'FUTURE_UNKNOWN'}, None)])
def test_mteam_promotion_precedence_and_unknown(status, factor):
    assert detail.parse_mteam(mteam(**status), '42')['downloadvolumefactor'] == factor


@pytest.mark.parametrize('payload', [mteam(), {'code': '401'}, {'code': 0, 'data': {}}])
def test_wrong_id_or_failure_never_accepted(payload):
    assert detail.parse_mteam(payload, '43') is None


def nexus(promotion='', count='8个做种者 | 0个下载者', extra=''):
    return f'''<html><h1 id="top">Show S01 {promotion}</h1>
      <table><tr><td><a href="download.php?id=42&amp;passkey=PRIVATE">download</a></td></tr>
      <tr><td><b>大小:</b> 1.5 GB</td></tr></table>
      <div id="peercount">{count}</div><a href="viewsnatches.php?id=42">125次</a>{extra}</html>'''


@pytest.mark.parametrize('promotion,factor', [('', 1), ('<font class="free">[Free]</font>', 0),
    ('<font class="twoupfree">[2X Free]</font>', 0), ('<font class="halfdown">[50%]</font>', 0.5),
    ('<font class="thirtypercent">[30%]</font>', 0.3),
    ('<font class="halfdown">[50%]</font><span class="twoupfree">(通过)</span>', 0.5),
    ('<span class="twoupfree">(通过)</span>', 1), ('<span>[10%]</span>', None)])
def test_nexus_promotions_not_confused_with_approval_or_recommendations(promotion, factor):
    result = detail.parse_nexus(nexus(promotion, extra='<div><font class="free">[Free]</font></div>'),
                                'https://source/details.php?id=42', '42')
    assert result['downloadvolumefactor'] == factor
    assert result['seeders'] == 8 and result['peers'] == 0 and result['grabs'] == 125
    assert result['size'] == 1610612736


@pytest.mark.parametrize('text', ['<h1>Login</h1>', nexus().replace('id=42', 'id=43'),
                                  nexus(extra='<input type="password">')])
def test_login_or_other_torrent_not_accepted(text):
    assert detail.parse_nexus(text, 'https://source/details.php?id=42', '42') is None


def test_zero_and_missing_seeders_are_not_conflated():
    assert detail.parse_mteam(mteam(seeders='0'), '42')['seeders'] == 0
    assert detail.parse_mteam(mteam(seeders=None), '42')['seeders'] is None
    assert detail.parse_nexus(nexus(count=''), 'https://source/details.php?id=42', '42')['seeders'] is None


def test_nexus_request_uses_site_cookie_ua_proxy_and_safe_link():
    request, calls = requester(text=nexus())
    config = site(domain='https://source/', schema='NexusPhp', apikey=None, cookie='COOKIE', ua='UA', proxy=True)
    result = detail.fetch_detail(config, '42', request, proxy={'https': 'proxy'})
    assert result.status == 'ready'
    assert calls[0][1]['cookies'] == 'COOKIE' and calls[0][1]['ua'] == 'UA'
    assert calls[0][1]['proxies'] == {'https': 'proxy'}
    assert result.torrent['page_url'] == 'https://source/details.php?id=42'


def test_known_api_site_does_not_guess_nexus_url():
    assert detail.detail_url(site(domain='https://other/', parser='RousiPro'), '42') is None
    assert detail.detail_url(site(), '../42') is None
    assert detail.detail_url(site(domain='https://source/', _seedrescue_nexus=True), '42') == 'https://source/details.php?id=42'


def test_direct_lookup_skips_search_and_deduplicates_same_id(plugin, monkeypatch):
    request, calls = requester(mteam())
    monkeypatch.setattr(host, 'RequestUtils', request)
    monkeypatch.setattr(host, 'TorrentsChain', lambda: pytest.fail('无需关键词搜索'))
    match = host.IyuuMatch(3, '42', 'b' * 40)
    entries = [(0, match, site()), (1, match, site())]
    results = plugin._probe_domain('m-team.cc', entries, 'title', {2: 0})
    assert len(calls) == 1
    assert all(r[1].seeders == 8 and r[2]['searches'] == 0 for r in results)
    job = {'target_hash': 'a' * 40}
    plugin._apply_candidates(job, [results[0][1]], [results[0][2]])
    record = job['candidates'][0]
    assert record['lookup_method'] == 'detail' and record['eligible']
    assert 'SECRET' not in str(plugin._job_view(job)) and 'genDlToken' not in str(record)


@pytest.mark.parametrize('code', [401, 403, 429, 500, 302])
def test_failed_detail_preserves_candidate_no_search_storm_or_download(plugin, monkeypatch, code):
    request, calls = requester(code=code)
    monkeypatch.setattr(host, 'RequestUtils', request)
    monkeypatch.setattr(host, 'TorrentsChain', lambda: pytest.fail('认证/网络/限流失败不追加搜索'))
    match = host.IyuuMatch(3, '42', 'b' * 40)
    result = plugin._probe_domain('m-team.cc', [(0, match, site())], 'title', {2: 0})[0]
    assert len(calls) == 1 and result[2]['matched']
    assert result[1].metadata_status == 'unavailable'
    assert result[1].torrent.page_url == 'https://kp.m-team.cc/detail/42'
    plugin._minimum_seeders = None
    plugin._selection_mode = 'auto'
    plugin._start_source = lambda *args: pytest.fail('未取得详情不得自动提交')
    job = {'target_hash': 'a' * 40}
    plugin._apply_candidates(job, [result[1]], [result[2]])
    assert job['state'] == 'WAITING_SOURCE_RETRY'
    assert len(job['candidates']) == 1 and job['candidates'][0]['eligible'] is False


def test_partial_detail_uses_id_checked_search_fallback(plugin, monkeypatch):
    request, _ = requester(mteam(discount=None))
    monkeypatch.setattr(host, 'RequestUtils', request)
    calls = []

    def browse(**kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(page_url='https://kp.m-team.cc/detail/42', enclosure='download',
                                seeders=9, downloadvolumefactor=0)]
    monkeypatch.setattr(host, 'TorrentsChain', lambda: SimpleNamespace(browse=browse))
    result = plugin._probe_domain('m-team.cc', [(0, host.IyuuMatch(3, '42', 'b' * 40), site())], 'title', {2: 0})[0]
    assert len(calls) == 1 and result[1].lookup_method == 'search' and result[1].seeders == 9


def test_configured_site_rate_limit_is_respected(plugin, monkeypatch):
    monkeypatch.setattr(host, 'SitesHelper', lambda: SimpleNamespace(check=lambda domain: (True, 'private message')))
    monkeypatch.setattr(host, 'RequestUtils', lambda **kwargs: pytest.fail('流控期间不得请求'))
    result = plugin._fetch_source_detail('m-team.cc', site(), '42')
    assert result.status == 'unavailable' and 'private' not in result.error


def test_unlimited_seeders_still_allows_verified_detail_with_unknown_count(plugin, monkeypatch):
    request, _ = requester(mteam(seeders=None))
    monkeypatch.setattr(host, 'RequestUtils', request)
    monkeypatch.setattr(host, 'TorrentsChain', lambda: SimpleNamespace(browse=lambda **kwargs: []))
    plugin._minimum_seeders = None
    result = plugin._probe_domain('m-team.cc', [(0, host.IyuuMatch(3, '42', 'b' * 40), site())], 'title', {2: 0})[0]
    assert result[1].metadata_status == 'ready'
    assert host.ranked_sources([result[1]], None, [host.NON_FREE]) == [result[1]]

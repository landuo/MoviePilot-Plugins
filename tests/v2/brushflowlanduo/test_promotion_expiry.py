import ast
import calendar
import random
import re
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin
from zoneinfo import ZoneInfo


PLUGIN_PATH = Path(__file__).parents[3] / "plugins.v2" / "brushflowlanduo" / "__init__.py"

# 每次装载测试宿主前收集 logger.warning，用于断言“失败不再静默”
WARNINGS: list = []
METHOD_NAMES = {
    "_parse_promotion_deadline",
    "_parse_promotion_zone",
    "_promotion_duration_seconds",
    "_promotion_expiry_from_diff",
    "_inferred_site_clock_offset",
    "_promotion_expiry_at",
    "_resolve_promotion_expiry",
    "_promotion_verify_due",
    "_promotion_expiry",
    "_parse_pubdate",
    "_refresh_promotion_from_site",
    "_get_task_site",
    "_record_added_as_free",
    "__site_cookie",
    "__parse_site_promotion_deadline",
    "__site_page_has_promotion",
    "__site_page_is_torrent",
    "__site_page_says_no_promotion",
    "__site_page_has_promotion_countdown",
    "__promotion_expired",
    "__log_promotion_unverified",
    "_now_iso",
}


def load_promotion_harness(host_tz: str = "Asia/Shanghai", request_utils=None):
    """按需抽取促销到期相关方法，避免导入 MoviePilot 运行时依赖"""
    WARNINGS.clear()
    source = PLUGIN_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "BrushFlowLanduo"
    )
    harness = ast.ClassDef(
        name="BrushFlowHarness",
        bases=[],
        keywords=[],
        decorator_list=[],
        body=[
            node for node in plugin_class.body
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in METHOD_NAMES
            ) or (
                isinstance(node, ast.Assign)
                and any(getattr(target, "id", "").startswith("PROMOTION_") for target in node.targets)
            )
        ],
    )
    namespace = {
        "BrushFlowLanduo": None,  # 占位，装载后替换为测试宿主
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "Tuple": Tuple,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "ZoneInfo": ZoneInfo,
        "threading": threading,
        "time": time,
        "random": random,
        "calendar": calendar,
        "urljoin": urljoin,
        "re": re,
        "logger": SimpleNamespace(
            warning=lambda *args, **kwargs: WARNINGS.append(" ".join(str(item) for item in args)),
            info=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
        "settings": SimpleNamespace(TZ=host_tz, USER_AGENT="Mozilla/5.0 Test", PROXY=None, NO_PROXY=False),
    }
    class _UnconfiguredRequestUtils:
        """未显式注入时禁止测试发起真实请求"""

        def __init__(self, *args, **kwargs):
            raise AssertionError("测试未注入 RequestUtils，不应发起真实请求")

    def _cookie_parse(value):
        """等价于 MoviePilot app.utils.http.cookie_parse 的最小实现"""
        parsed = {}
        for part in str(value or "").split(";"):
            if "=" in part:
                key, _, item = part.partition("=")
                if key.strip():
                    parsed[key.strip()] = item.strip()
        return parsed

    namespace["cookie_parse"] = _cookie_parse
    namespace["RequestUtils"] = request_utils or _UnconfiguredRequestUtils
    exec(
        compile(ast.fix_missing_locations(ast.Module(body=[harness], type_ignores=[])), str(PLUGIN_PATH), "exec"),
        namespace,
    )
    namespace["BrushFlowLanduo"] = namespace["BrushFlowHarness"]
    return namespace


HOST_TZ = "Asia/Shanghai"


def host_local(value: datetime) -> datetime:
    return value.astimezone(ZoneInfo(HOST_TZ))


class ParsePromotionDeadlineTests(unittest.TestCase):
    """_promotion_expiry_at 必须能吃下站点列表页/RSS 里常见的各种促销文本"""

    def setUp(self):
        self.plugin = load_promotion_harness()["BrushFlowHarness"]()

    def parse(self, value, offset=0):
        return self.plugin._promotion_expiry_at(value, offset)

    def assert_local(self, value, expected: datetime, offset: float = 0):
        result = self.parse(value, offset)
        self.assertIsNotNone(result, f"{value!r} 未能解析出促销截止时间")
        self.assertEqual(host_local(result), host_local(expected))

    def test_full_datetime_is_site_local_time(self):
        self.assert_local("2026-09-20 12:00:00", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_datetime_without_seconds(self):
        self.assert_local("2026-09-20 12:00", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_date_only_defaults_to_end_of_day(self):
        self.assert_local("2026-09-20", datetime(2026, 9, 20, 23, 59, 59, tzinfo=ZoneInfo(HOST_TZ)))

    def test_slash_separator(self):
        self.assert_local("2026/09/20 12:00:00", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_dot_separator_with_single_digit_parts(self):
        self.assert_local("2026.9.3 08:30", datetime(2026, 9, 3, 8, 30, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_iso_datetime_with_utc_marker_is_converted(self):
        self.assert_local("2026-09-20T12:00:00Z", datetime(2026, 9, 20, 20, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_explicit_numeric_offset_is_respected(self):
        # +0800 == 宿主时区，挂钟时间保持不变
        self.assert_local("2026-09-20 12:00:00 +0800", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_iso_datetime_with_colon_offset_is_respected(self):
        # +0800 == 宿主时区，挂钟时间保持不变
        self.assert_local("2026-09-20T12:00:00+08:00", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_chinese_prefix_and_suffix_are_ignored(self):
        self.assert_local("免费截止 2026-09-20 12:00:00", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))
        self.assert_local("2026-09-20 12:00:00 到期", datetime(2026, 9, 20, 12, 0, 0, tzinfo=ZoneInfo(HOST_TZ)))

    def test_relative_duration_is_expanded_from_now(self):
        before = datetime.now(ZoneInfo(HOST_TZ))
        result = self.parse("剩余 2小时30分")
        self.assertIsNotNone(result, "相对剩余时间未能解析")
        expected = before + timedelta(hours=2, minutes=30)
        self.assertLess(abs((result - expected).total_seconds()), 120)

    def test_relative_days_hours_minutes(self):
        before = datetime.now(ZoneInfo(HOST_TZ))
        result = self.parse("2天3小时5分")
        self.assertIsNotNone(result, "相对剩余时间未能解析")
        expected = before + timedelta(days=2, hours=3, minutes=5)
        self.assertLess(abs((result - expected).total_seconds()), 120)

    def test_timezone_offset_shifts_site_local_deadline(self):
        self.assert_local("2026-09-20 12:00:00", datetime(2026, 9, 20, 4, 0, 0, tzinfo=ZoneInfo(HOST_TZ)), offset=-8)
        self.assert_local("2026-09-20 12:00:00", datetime(2026, 9, 20, 20, 0, 0, tzinfo=ZoneInfo(HOST_TZ)), offset=8)

    def test_blank_input_returns_none(self):
        self.assertIsNone(self.parse(None))
        self.assertIsNone(self.parse(""))
        self.assertIsNone(self.parse("   "))

    def test_unparsable_text_returns_none(self):
        self.assertIsNone(self.parse("暂无"))
        self.assertIsNone(self.parse("免费"))


class PromotionDurationTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_promotion_harness()["BrushFlowHarness"]()

    def test_duration_from_moviepilot_freedate_diff(self):
        self.assertEqual(self.plugin._promotion_duration_seconds("2天3小时"), (2 * 24 + 3) * 3600)
        self.assertEqual(self.plugin._promotion_duration_seconds("5小时30分钟"), 5 * 3600 + 30 * 60)
        self.assertEqual(self.plugin._promotion_duration_seconds("45分钟"), 45 * 60)
        self.assertEqual(
            self.plugin._promotion_duration_seconds("1 day, 2:03:04"),
            26 * 3600 + 3 * 60 + 4,
        )

    def test_duration_ignores_values_without_units(self):
        self.assertIsNone(self.plugin._promotion_duration_seconds("--"))
        self.assertIsNone(self.plugin._promotion_duration_seconds(None))


class SiteClockOffsetTests(unittest.TestCase):
    """站点时间与宿主时间的偏差必须能自动推导，避免删除时间整体偏移若干小时"""

    def setUp(self):
        self.plugin = load_promotion_harness()["BrushFlowHarness"]()

    def infer(self, published_at: datetime, added_on: float):
        return self.plugin._inferred_site_clock_offset(published_at, added_on)

    def test_utc_site_on_shanghai_host(self):
        """UTC 站点在 UTC+8 宿主上应得到 +480 分钟：站点时间 + 480 分钟 = 宿主时间"""
        now = datetime.now(ZoneInfo(HOST_TZ))
        published_site_local = (now - timedelta(minutes=30)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        offset = self.infer(published_site_local, now.timestamp() - 28 * 60)
        self.assertEqual(offset, 480)

    def test_same_zone_site_on_shanghai_host(self):
        now = datetime.now(ZoneInfo(HOST_TZ))
        offset = self.infer(now.replace(tzinfo=None) - timedelta(minutes=30), now.timestamp() - 28 * 60)
        self.assertEqual(offset, 0)

    def test_utc_plus_two_site_on_shanghai_host(self):
        """UTC+2 站点在 UTC+8 宿主上应得到 +360 分钟"""
        now = datetime.now(ZoneInfo(HOST_TZ))
        published_site_local = (now - timedelta(minutes=30)).astimezone(ZoneInfo("Etc/GMT-2")).replace(tzinfo=None)
        offset = self.infer(published_site_local, now.timestamp() - 29 * 60)
        self.assertEqual(offset, 360)

    def test_utc_site_on_utc_host(self):
        plugin = load_promotion_harness(host_tz="UTC")["BrushFlowHarness"]()
        now = datetime.now(ZoneInfo("UTC"))
        offset = plugin._inferred_site_clock_offset(now.replace(tzinfo=None) - timedelta(minutes=10), now.timestamp() - 600)
        self.assertEqual(offset, 0)

    def test_utc_site_on_new_york_host(self):
        plugin = load_promotion_harness(host_tz="America/New_York")["BrushFlowHarness"]()
        now = datetime.now(ZoneInfo("America/New_York"))
        published_site_local = (now - timedelta(minutes=20)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        offset = plugin._inferred_site_clock_offset(published_site_local, now.timestamp() - 18 * 60)
        self.assertEqual(offset, -240)

    def test_offset_is_stable_for_late_additions(self):
        """间隔较久才加入下载器时，四舍五入到整点仍应得到正确时区"""
        now = datetime.now(ZoneInfo(HOST_TZ))
        published_site_local = (now - timedelta(hours=6)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        offset = self.infer(published_site_local, now.timestamp() - 5 * 3600)
        # 加入时刻与发布时刻存在数小时误差时仍能推导出小时级时区（允许整点取整带来的 1 小时误差）
        self.assertIn(abs(offset), {420, 480, 540})

    def test_missing_inputs_are_ignored(self):
        self.assertIsNone(self.infer(None, time.time()))
        self.assertIsNone(self.infer(datetime.now(), 0))
        self.assertIsNone(self.infer(datetime.now(), time.time() + 86400))


class PromotionExpiredTests(unittest.TestCase):
    """__promotion_expired: 只有确认促销结束才允许跳过删除，未确认时应给出原因"""

    def make_task(self, **overrides):
        values = {
            "del_no_free": True,
            "timezone_offset": 0,
            "promo_max_hours": None,
            "rss_support": False,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def build(self, task):
        namespace = load_promotion_harness()
        harness = namespace["BrushFlowHarness"]
        harness._get_task_config = lambda self=None: task
        instance = harness()
        # 这些用例只验证本地判定，站点探测单独测试，避免发起真实请求
        instance._get_task_site = lambda: None
        return instance

    def test_expired_deadline_deletes_incomplete_download(self):
        instance = self.build(self.make_task())
        past = (datetime.now(ZoneInfo(HOST_TZ)) - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": past},
        )
        self.assertTrue(expired)
        self.assertEqual(reason, "促销已过期")

    def test_future_deadline_keeps_download(self):
        instance = self.build(self.make_task())
        future = (datetime.now(ZoneInfo(HOST_TZ)) + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": future},
        )
        self.assertFalse(expired)
        self.assertEqual(reason, "")

    def test_utc_site_deadline_is_auto_corrected(self):
        """站点显示 UTC、任务时区留 0 时，UTC 截止时间必须换算到宿主时区再判断"""
        instance = self.build(self.make_task())
        now = datetime.now(ZoneInfo(HOST_TZ))
        published_utc = (now - timedelta(minutes=20)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        # UTC 站点显示“还有 10 分钟”，换算成宿主时间后仍应在未来
        deadline_utc = (now + timedelta(minutes=10)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {
                "downloaded": 100,
                "total_size": 1000,
                "add_on": time.time() - 18 * 60,
                "pubdate": published_utc.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {"freedate": deadline_utc.strftime("%Y-%m-%d %H:%M:%S")},
        )
        self.assertFalse(expired, "UTC 站点的未来截止时间不应被当成已过期")

        # 已经过去的 UTC 截止时间必须被识别为过期
        past_utc = (now - timedelta(minutes=10)).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {
                "downloaded": 100,
                "total_size": 1000,
                "add_on": time.time() - 18 * 60,
                "pubdate": published_utc.strftime("%Y-%m-%d %H:%M:%S"),
            },
            {"freedate": past_utc.strftime("%Y-%m-%d %H:%M:%S")},
        )
        self.assertTrue(expired, "UTC 站点的过期截止时间必须被识别，否则种子会被计费下载")
        self.assertIn("自动校正", reason)

    def test_rss_task_is_not_auto_corrected(self):
        """RSS 发布时间已被主程序换算为宿主时区，不能再做时区校正"""
        instance = self.build(self.make_task(rss_support=True))
        now = datetime.now(ZoneInfo(HOST_TZ))
        past_host = (now - timedelta(minutes=10)).replace(tzinfo=None)
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {
                "downloaded": 100,
                "total_size": 1000,
                "add_on": time.time() - 18 * 60,
                "pubdate": (now - timedelta(minutes=20)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
            },
            {"freedate": past_host.strftime("%Y-%m-%d %H:%M:%S")},
        )
        self.assertTrue(expired)
        self.assertNotIn("自动校正", reason)

    def test_completed_download_is_never_deleted(self):
        instance = self.build(self.make_task())
        past = (datetime.now(ZoneInfo(HOST_TZ)) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
        expired, _ = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 1000, "total_size": 1000},
            {"freedate": past},
        )
        self.assertFalse(expired)

    def test_relative_countdown_is_expanded_at_check_time(self):
        instance = self.build(self.make_task())
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {
                "freedate": None,
                "freedate_diff": "2小时",
                "add_on": time.time() - 3 * 3600,
            },
        )
        self.assertTrue(expired, "列表页只给倒计时文本时也必须能判定促销已过期")
        self.assertIn("促销", reason)

    def test_missing_deadline_reports_unverified_instead_of_silence(self):
        instance = self.build(self.make_task())
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": None, "title": "某某种子"},
        )
        self.assertFalse(expired)
        self.assertEqual(reason, "")
        self.assertTrue(
            any("促销截止时间缺失或无法解析" in item for item in WARNINGS),
            "无法确认促销截止时间时必须留下诊断日志，而不是静默跳过",
        )

    def test_del_no_free_disabled_keeps_silent(self):
        instance = self.build(self.make_task(del_no_free=False))
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": None},
        )
        self.assertFalse(expired)
        self.assertEqual(reason, "")

    def test_promo_max_hours_safety_net(self):
        instance = self.build(self.make_task(promo_max_hours=24))
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": None, "add_on": time.time() - 30 * 3600},
        )
        self.assertTrue(expired, "配置兜底时长后，长期未完成的免费种子应被清理")
        self.assertIn("兜底", reason)

    def test_promo_max_hours_does_not_fire_early(self):
        instance = self.build(self.make_task(promo_max_hours=24))
        expired, _ = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": None, "add_on": time.time() - 2 * 3600},
        )
        self.assertFalse(expired)


class UbitsMarkupTests(unittest.TestCase):
    """ubits.club 列表页真实促销标记：模板选择器用了子代组合器，因此匹配不到"""

    # 摘自 ubits.club 列表页（NexusPHP classic UI）免费种子的实际标记
    ROW_MARKUP = (
        "<td>"
        "<font color='#0000FF'size=2 ><b>剩余时间：<span title=\"2026-09-20 22:56:09\">23时1分钟</span></b></font>"
        "</td>"
    )
    # MoviePilot 站点配置（resources.v2/user.sites.v2.bin）中 ubits 的 freedate 选择器
    SHIPPED_SELECTOR = "font[color] > span[title]"
    # 可行写法：改用后代组合器，跳过站点插入的 <b>
    WORKING_SELECTOR = "font[color] span[title]"

    def test_site_inserts_between_font_and_span(self):
        self.assertIn("<b>剩余时间：<span title=", self.ROW_MARKUP)
        self.assertNotIn("</b><span", self.ROW_MARKUP)

    def test_shipped_child_combinator_selector_misses_ubits_markup(self):
        direct_child = re.search(r"<font[^>]*>\s*<span title=\"([^\"]+)\"", self.ROW_MARKUP)
        self.assertIsNone(direct_child, f"{self.SHIPPED_SELECTOR} 在 ubits 标记上不应命中")

    def test_descendant_selector_finds_deadline_and_parses(self):
        found = re.search(r"<font[^>]*>.*?<span title=\"([^\"]+)\"", self.ROW_MARKUP, re.S)
        self.assertIsNotNone(found, f"{self.WORKING_SELECTOR} 必须能取到截止时间")
        instance = load_promotion_harness()["BrushFlowHarness"]()
        # 站点为 UTC+8 且宿主也是 UTC+8 时，timezone_offset 应为 0，截止时间按站点本地时间使用
        expiry = instance._promotion_expiry_at(found.group(1), 0)
        self.assertIsNotNone(expiry)
        self.assertEqual(expiry.strftime("%Y-%m-%d %H:%M:%S"), "2026-09-20 22:56:09")

    def test_broken_selector_result_still_raises_visible_warning(self):
        """选择器抓不到时 freedate 为 None：必须留下可排查的日志，而不是静默失效"""
        instance = load_promotion_harness()["BrushFlowHarness"]()
        task = SimpleNamespace(del_no_free=True, timezone_offset=0, promo_max_hours=None, rss_support=False)
        instance._get_task_config = lambda task_id=None: task
        # 该用例模拟“站点探测也拿不到截止时间”（例如没有详情页地址）
        instance._get_task_site = lambda: None
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000},
            {"freedate": None, "title": "ubits 种子"},
        )
        self.assertFalse(expired)
        self.assertEqual(reason, "")
        self.assertTrue(any("促销截止时间缺失或无法解析" in item for item in WARNINGS))


class FakeResponse:
    def __init__(self, text):
        self.text = text


class RecordingRequestUtils:
    """记录请求参数的 RequestUtils 替身"""

    calls = []

    def __init__(self, ua=None, cookies=None, proxies=None, timeout=None, **kwargs):
        self.kwargs = {"ua": ua, "cookies": cookies, "proxies": proxies, "timeout": timeout}
        RecordingRequestUtils.calls.append(self.kwargs)
        self.response = None

    def get_res(self, url, **kwargs):
        self.url = url
        self.get_kwargs = kwargs
        return self.response


class SiteProbeTests(unittest.TestCase):
    """存储的 freedate 无法判定时，插件应直接读取站点页面的促销信息补齐"""

    FREE_PAGE = (
        "<html><body><table><tr>"
        "<img class=\"pro_free\" alt=\"Free\">"
        "<font color='#0000FF'size=2 ><b>剩余时间：<span title=\"2099-01-01 00:00:00\">23时1分钟</span></b></font>"
        "</tr></table></body></html>"
    )
    EXPIRED_PAGE = (
        "<html><body><table><tr>"
        "<font color='#0000FF'size=2 ><b>剩余时间：<span title=\"2020-01-01 00:00:00\">0分钟</span></b></font>"
        "</tr></table></body></html>"
    )
    # 站点明确声明“当前无优惠”且页面没有促销剩余时间，即促销已结束
    NO_PROMO_PAGE = (
        "<html><body><td class='rowfollow'>2026-09-20 00:04:41</td>"
        "<a href='download.php?id=364105'>下载</a>"
        "<span title='盒子当前不享受种子促销'>无优惠（2026-10-03 21:05 后恢复正常促销）</span>"
        "</body></html>"
    )
    # 只是抓不到促销标记、站点也没说“无优惠”时不能判定删除
    UNKNOWN_PROMO_PAGE = (
        "<html><body><td class='rowfollow'>2026-09-20 00:04:41</td>"
        "<a href='download.php?id=364105'>下载</a></body></html>"
    )
    # ubits 列表页真实标记：font 与 span 之间插入了 <b>
    UBITS_PAGE = (
        "<font color='#0000FF'size=2 ><b>剩余时间："
        "<span title=\"2099-01-01 00:00:00\">23时1分钟</span></b></font>"
    )

    def build(self, page_text, record=None, site=None):
        response = FakeResponse(page_text)

        class Recorder(RecordingRequestUtils):
            calls = []

            def get_res(self, url, **kwargs):
                self.url = url
                Recorder.calls.append({"url": url, **self.kwargs})
                return response

        # RequestUtils 必须在装载测试宿主之前注入，方法与模块共享同一命名空间
        namespace = load_promotion_harness(request_utils=Recorder)
        harness = namespace["BrushFlowHarness"]
        instance = harness()
        instance._get_task_site = lambda: site
        return instance, Recorder, (record if record is not None else {
            "title": "某某种子",
            "page_url": "https://ubits.club/details.php?id=364105&hit=1&ubits_ui=classic",
            "downloadvolumefactor": 0,
        })

    def test_probe_reads_active_deadline_from_details_page(self):
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie="a=1; b=2",
                              ua="Mozilla/5.0", proxy=0, timeout=15)
        instance, recorder, record = self.build(self.FREE_PAGE, site=site)
        self.assertTrue(instance._refresh_promotion_from_site(record), "主动促销应被识别")
        self.assertEqual(record["freedate"], "2099-01-01 00:00:00")
        self.assertNotIn("promotion_ended_at", record)
        self.assertEqual(recorder.calls[0]["cookies"], {"a": "1", "b": "2"})
        # 详情页是绝对地址，不应被域名重复拼接
        self.assertEqual(recorder.calls[0]["url"], record["page_url"])

    def test_probe_marks_ended_when_countdown_passed(self):
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, _, record = self.build(self.EXPIRED_PAGE, site=site)
        self.assertTrue(instance._refresh_promotion_from_site(record))
        self.assertTrue(record.get("promotion_ended_at"), "倒计时已走完应判定促销结束")

    def test_probe_marks_ended_when_page_has_no_promotion(self):
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, _, record = self.build(self.NO_PROMO_PAGE, site=site)
        self.assertTrue(instance._refresh_promotion_from_site(record))
        self.assertTrue(record.get("promotion_ended_at"))

    def test_probe_handles_broken_selector_markup(self):
        """选择器抓不到 freedate 时，探测必须能从同一段标记里拿到截止时间"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, _, record = self.build(self.UBITS_PAGE, site=site)
        self.assertTrue(instance._refresh_promotion_from_site(record))
        self.assertEqual(record["freedate"], "2099-01-01 00:00:00")

    def test_probe_is_throttled_within_interval(self):
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, recorder, record = self.build(self.NO_PROMO_PAGE, site=site)
        record["promotion_probe_at"] = time.time()
        self.assertFalse(instance._refresh_promotion_from_site(record), "刚探测过的记录不应重复请求")
        self.assertEqual(len(recorder.calls), 0)

    def test_probe_runs_again_after_interval(self):
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, recorder, record = self.build(self.FREE_PAGE, site=site)
        record["promotion_probe_at"] = time.time() - instance.PROMOTION_PROBE_INTERVAL - 1
        self.assertTrue(instance._refresh_promotion_from_site(record))
        self.assertEqual(len(recorder.calls), 1)

    def test_cached_deadline_is_reverified_and_early_end_deletes(self):
        """站点在截止时间前提前结束促销：复核必须发现并立即删除"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        task = SimpleNamespace(del_no_free=True, timezone_offset=0, promo_max_hours=None, rss_support=False)
        # 站点页面：倒计时已被替换为“无优惠”，即促销提前结束
        instance, recorder, record = self.build(self.NO_PROMO_PAGE, site=site)
        instance._get_task_config = lambda task_id=None: task
        future = (datetime.now(ZoneInfo(HOST_TZ)) + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        record.update({
            "freedate": future,
            "downloadvolumefactor": 0,
            "add_on": time.time() - 3600,
            "promotion_probe_at": time.time() - instance.PROMOTION_VERIFY_INTERVAL - 3600,
        })
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000, "add_on": record["add_on"]}, record)
        self.assertTrue(expired, "站点提前结束促销时必须立即删除，而不是等原定截止时间")
        self.assertIn("站点已无促销", reason)

    def test_cached_deadline_without_due_reverification_is_kept(self):
        """距上次探测不足复核间隔时不重复请求，按已知截止时间处理"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        task = SimpleNamespace(del_no_free=True, timezone_offset=0, promo_max_hours=None, rss_support=False)
        instance, recorder, record = self.build(self.NO_PROMO_PAGE, site=site)
        instance._get_task_config = lambda task_id=None: task
        future = (datetime.now(ZoneInfo(HOST_TZ)) + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        record.update({
            "freedate": future,
            "downloadvolumefactor": 0,
            "add_on": time.time() - 3600,
            "promotion_probe_at": time.time() - 60,
        })
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000, "add_on": record["add_on"]}, record)
        self.assertFalse(expired)
        self.assertEqual(recorder.calls, [], "复核间隔未到时不应请求站点")

    def test_cached_deadline_still_active_after_reverify_is_kept(self):
        """复核后促销仍在进行：写回新的截止时间并继续等待"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        task = SimpleNamespace(del_no_free=True, timezone_offset=0, promo_max_hours=None, rss_support=False)
        page = ("<html><a href='download.php?id=1'>x</a>"
                "<font color='#0000FF'><b>剩余时间：<span title='2099-01-01 00:00:00'>x</span></b></font></html>")
        instance, recorder, record = self.build(page, site=site)
        instance._get_task_config = lambda task_id=None: task
        future = (datetime.now(ZoneInfo(HOST_TZ)) + timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        record.update({
            "freedate": future,
            "downloadvolumefactor": 0,
            "add_on": time.time() - 3600,
            "promotion_probe_at": time.time() - instance.PROMOTION_VERIFY_INTERVAL - 3600,
        })
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000, "add_on": record["add_on"]}, record)
        self.assertFalse(expired)
        self.assertTrue(recorder.calls, "到复核间隔后应重新读取站点促销状态")
        self.assertEqual(record["freedate"], "2099-01-01 00:00:00")

    def test_verify_cadence_densifies_near_deadline(self):
        """越接近截止时间，复核越频繁"""
        plugin = load_promotion_harness()["BrushFlowHarness"]()
        now = time.time()
        far = datetime.now(ZoneInfo(HOST_TZ)) + timedelta(hours=24)
        near = datetime.now(ZoneInfo(HOST_TZ)) + timedelta(minutes=6)
        probed_40m_ago = {"promotion_probe_at": now - 40 * 60}
        probed_25m_ago = {"promotion_probe_at": now - 25 * 60}
        # 默认基础复核间隔为 30 分钟：剩余时间长时 25 分钟内不复核、超过 30 分钟后复核
        self.assertFalse(
            plugin._promotion_verify_due(probed_25m_ago, now, far),
            "剩余 24 小时时不应在基础复核间隔内重复请求",
        )
        self.assertTrue(
            plugin._promotion_verify_due(probed_40m_ago, now, far),
            "超过基础复核间隔后应重新核对站点促销状态",
        )
        self.assertTrue(
            plugin._promotion_verify_due(probed_25m_ago, now, near),
            "临近截止时间时必须提高复核频率",
        )
        # 下限不能把临近到期的复核频率卡住
        half_hour = datetime.now(ZoneInfo(HOST_TZ)) + timedelta(minutes=30)
        six_minutes = datetime.now(ZoneInfo(HOST_TZ)) + timedelta(minutes=6)
        self.assertTrue(
            plugin._promotion_verify_due({"promotion_probe_at": now - 8 * 60}, now, half_hour),
            "剩余 30 分钟时应约每 5 分钟复核一次",
        )
        self.assertTrue(
            plugin._promotion_verify_due({"promotion_probe_at": now - 5 * 60}, now, six_minutes),
            "剩余数分钟时应每 1 分钟左右复核一次",
        )

    def test_never_probed_records_are_not_reverified(self):
        """截止时间来自列表页快照（从未探测）时不做额外站点请求"""
        plugin = load_promotion_harness()["BrushFlowHarness"]()
        now = time.time()
        future = datetime.now(ZoneInfo(HOST_TZ)) + timedelta(hours=2)
        self.assertFalse(plugin._promotion_verify_due({"freedate": "2099-01-01 00:00:00"}, now, future))

    def test_probe_skips_non_free_records(self):
        """普通种子（下载因子不为 0）不应触发促销探测"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, recorder, record = self.build(
            self.FREE_PAGE,
            record={"title": "普通种子", "page_url": "https://ubits.club/details.php?id=1",
                    "downloadvolumefactor": 1},
            site=site,
        )
        self.assertFalse(instance._refresh_promotion_from_site(record))
        self.assertEqual(recorder.calls, [])

    def test_probe_skips_without_page_url_or_site(self):
        instance, recorder, record = self.build(self.FREE_PAGE, record={"title": "无地址", "downloadvolumefactor": 0})
        self.assertFalse(instance._refresh_promotion_from_site(record))
        self.assertEqual(recorder.calls, [])

    def test_relative_page_url_is_joined_with_site_domain(self):
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, recorder, record = self.build(self.FREE_PAGE, site=site)
        record["page_url"] = "/details.php?id=364105"
        self.assertTrue(instance._refresh_promotion_from_site(record))
        self.assertEqual(recorder.calls[0]["url"], "https://ubits.club/details.php?id=364105")

    def test_bad_pages_never_trigger_deletion(self):
        """RSS、登录页、用户页等无法证明促销结束时，不能判定删除"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        bad_pages = {
            "RSS(无促销但有详情链接)": "<rss><channel><item><link>https://ubits.club/details.php?id=1</link>"
                                      "<enclosure url=\"https://ubits.club/download.php?id=1\"/></item></channel></rss>",
            "登录页": "<html><form action='takelogin.php'><input name='username'></form></html>",
            "站点用户页": "<html><table><td class='rowfollow'>上传量</td></table></html>",
            "空页面": "<html></html>",
        }
        for label, page in bad_pages.items():
            with self.subTest(page=label):
                instance, recorder, record = self.build(page, site=site)
                self.assertFalse(
                    instance._refresh_promotion_from_site(record),
                    f"{label} 不应被判定为促销结束",
                )
                self.assertNotIn("promotion_ended_at", record)
                # 非种子页面同样记录探测时间，避免 Cookie 失效时高频重试
                self.assertIsNotNone(record.get("promotion_probe_at"))

    def test_unknown_promotion_state_is_not_deleted(self):
        """页面既无促销标记也无“无优惠”声明时，不能判定促销结束"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        instance, _, record = self.build(self.UNKNOWN_PROMO_PAGE, site=site)
        self.assertFalse(instance._refresh_promotion_from_site(record))
        self.assertNotIn("promotion_ended_at", record)

    def test_related_torrents_promo_tags_do_not_count(self):
        """同一详情页其他版本种子的 pro_50pctdown 标记不能当成当前种子的促销"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        page = (
            "<html><a href='download.php?id=364105'>下载</a>"
            "<span title='盒子当前不享受种子促销'>无优惠（2026-10-03 21:05 后恢复正常促销）</span>"
            "<tr><td><a href='details.php?id=294375'>Jaws 1080p</a>"
            "<img class='pro_50pctdown' src='pic/trans.gif' alt='50%'></td></tr>"
            "</html>"
        )
        instance, _, record = self.build(page, site=site)
        self.assertTrue(instance._refresh_promotion_from_site(record))
        self.assertTrue(record.get("promotion_ended_at"), "只应依据当前种子的促销状态判定")

    def test_page_with_other_promotion_is_not_deleted(self):
        """只有 50% 优惠、没有免费倒计时时应保持观察而不是删除"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        page = ("<html><a href='download.php?id=1'>下载</a>"
                "<img class=\"pro_50pctdown\" alt=\"50%\"></html>")
        instance, _, record = self.build(page, site=site)
        self.assertFalse(instance._refresh_promotion_from_site(record))
        self.assertNotIn("promotion_ended_at", record)

    def test_expired_promotion_is_deleted_via_probe(self):
        """完整链路：freedate 缺失 -> 探测发现已无促销 -> 判定删除"""
        site = SimpleNamespace(url="https://ubits.club", domain="ubits.club", cookie=None, ua=None, proxy=0, timeout=15)
        task = SimpleNamespace(del_no_free=True, timezone_offset=0, promo_max_hours=None, rss_support=False)
        instance, _, record = self.build(self.NO_PROMO_PAGE, site=site)
        instance._get_task_config = lambda task_id=None: task
        expired, reason = instance._BrushFlowHarness__promotion_expired(
            {"downloaded": 100, "total_size": 1000, "add_on": time.time() - 3600},
            record,
        )
        self.assertTrue(expired, "站点已无促销时必须删除未完成的下载")
        self.assertIn("促销", reason)


if __name__ == "__main__":
    unittest.main()

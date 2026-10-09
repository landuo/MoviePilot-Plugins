"""按站点种子 ID 读取详情；解析失败不等于 IYUU 映射不存在。"""

import base64
import json
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlparse

from lxml import html

from .core import extract_torrent_id, safe_page_url


@dataclass
class DetailResult:
    torrent: Optional[dict] = None
    status: str = "unsupported"
    error: Optional[str] = None


def site_base(site: dict) -> Optional[str]:
    return safe_page_url(site.get("url") or site.get("domain"))


def is_mteam(site: dict) -> bool:
    host = urlparse(site_base(site) or "").hostname or ""
    return bool(re.fullmatch(r"(?:[a-z0-9-]+\.)?m-team\.(?:cc|io)", host))


def detail_url(site: dict, torrent_id: str) -> Optional[str]:
    base = site_base(site)
    if not base or not str(torrent_id).isdigit():
        return None
    if is_mteam(site):
        host = urlparse(base).hostname
        return f"https://kp.m-team.{host.rsplit('.', 1)[-1]}/detail/{torrent_id}"
    # 特殊 API/前端站点不能猜成 NexusPHP 的详情地址。
    if site.get("parser") or not (site.get("_seedrescue_nexus")
                                 or str(site.get("schema") or "").lower().startswith("nexus")):
        return None
    return urljoin(base, f"details.php?id={torrent_id}")


def number(value) -> Optional[int]:
    value = str(value if value is not None else "").strip().replace(",", "")
    return int(value) if value.isdigit() else None


def parse_mteam(payload: dict, torrent_id: str) -> Optional[dict]:
    if not isinstance(payload, dict) or str(payload.get("code")) != "0":
        return None
    data = payload.get("data")
    if not isinstance(data, dict) or str(data.get("id")) != torrent_id:
        return None
    status = data.get("status") or {}
    if not isinstance(status, dict) or status.get("banned") is True:
        return None
    discount = status.get("discount")
    rule = status.get("promotionRule")
    if isinstance(rule, dict) and rule:
        discount = rule.get("discount")
    personal = status.get("mallSingleFree")
    if isinstance(personal, dict) and personal.get("status") == "ONGOING":
        discount = "FREE"
    factors = {"NORMAL": 1, "_2X": 1, "FREE": 0, "_2X_FREE": 0,
               "PERCENT_50": 0.5, "_2X_PERCENT_50": 0.5, "PERCENT_70": 0.3}
    return {
        "title": data.get("name"), "size": number(data.get("size")),
        "seeders": number(status.get("seeders")), "peers": number(status.get("leechers")),
        "grabs": number(status.get("timesCompleted")),
        "downloadvolumefactor": factors.get(discount),
    }


def parse_nexus(text: str, page_url: str, torrent_id: str) -> Optional[dict]:
    """只解析本种详情的标题及统计区域，不读取其他版本、简介或评论中的促销。"""
    doc = html.fromstring(text)
    headings = doc.xpath('//h1[@id="top"]') or doc.xpath('//h1')
    if not headings or doc.xpath('//input[@type="password"]'):
        return None
    enclosure = None
    for link in doc.xpath('//a[@href]'):
        url = urljoin(page_url, link.get("href"))
        if (urlparse(url).path.endswith("/download.php")
                and urlparse(url).netloc == urlparse(page_url).netloc
                and extract_torrent_id(url) == torrent_id):
            enclosure = url
            break
    if not enclosure:
        return None
    heading = headings[0]
    # 某些站点用 twoupfree 样式显示“审核通过”，不能仅凭 CSS class 判免费。
    labels = " ".join(heading.xpath('.//text()')[1:])
    factor = 1
    if re.search(r"(?i)(?:\[|【)\s*(?:\d+\s*[xX]\s*)?(?:free|免费|免費)\s*(?:\]|】)", labels):
        factor = 0
    elif re.search(r"(?i)(?:\[|【)\s*(?:\d+\s*[xX]\s*)?50%\s*(?:\]|】)", labels):
        factor = 0.5
    elif re.search(r"(?:\[|【)\s*30%\s*(?:\]|】)", labels):
        factor = 0.3
    elif re.search(r"(?i)free|免费|免費|\d+%|促销|促銷", labels):
        factor = None  # 非标准促销标记留给搜索适配器，禁止猜测免费。
    peers = doc.xpath('//*[@id="peercount"]')
    counts = re.findall(r"\d[\d,]*", peers[0].text_content()) if peers else []
    grabs = None
    for link in doc.xpath('//a[contains(@href, "viewsnatches.php")]'):
        if extract_torrent_id(link.get("href")) == torrent_id:
            count = re.search(r"\d[\d,]*", link.text_content())
            grabs = number(count.group()) if count else None
            break
    size = None
    for label in doc.xpath('//td//b'):
        if re.fullmatch(r"\s*(?:大小|體積|体积|Size)\s*[:：]?\s*", label.text_content(), re.I):
            value = re.search(r"([\d,.]+)\s*([KMGT]i?B|bytes|字节)", label.tail or "", re.I)
            if value:
                unit = value.group(2).upper()
                power = "KMGT".index(unit[0]) + 1 if unit[0] in "KMGT" else 0
                size = int(float(value.group(1).replace(",", "")) * 1024 ** power)
                break
    return {"title": (heading.text or heading.text_content()).strip(), "page_url": page_url,
            "enclosure": enclosure, "seeders": number(counts[0]) if counts else None,
            "peers": number(counts[1]) if len(counts) > 1 else None,
            "grabs": grabs, "size": size, "downloadvolumefactor": factor}


def fetch_detail(site: dict, torrent_id: str, request_factory, proxy=None, user_agent="") -> DetailResult:
    """每个 ID 最多一次详情请求。认证/限流/网络失败不追加关键词搜索。"""
    page = detail_url(site, torrent_id)
    if not page:
        return DetailResult(error="该站暂未适配按 ID 查详情")
    ua = site.get("ua") or user_agent
    kwargs = dict(ua=ua, proxies=proxy if site.get("proxy") else None,
                  timeout=min(int(site.get("timeout") or 15), 20))
    try:
        if is_mteam(site):
            if not site.get("apikey"):
                return DetailResult(status="unavailable", error="站点未配置 API Key")
            host = urlparse(site_base(site)).hostname
            api_host = host if host.startswith(("api.", "api2.")) else f"api.m-team.{host.rsplit('.', 1)[-1]}"
            api = f"https://{api_host}/api/torrent/"
            headers = {"x-api-key": site["apikey"]}
            response = request_factory(**kwargs, headers=headers).post_res(
                api + "detail", data={"id": torrent_id}, allow_redirects=False)
        else:
            response = request_factory(**kwargs, cookies=site.get("cookie")).get_res(page, allow_redirects=False)
        if response is None or response.status_code != 200:
            code = getattr(response, "status_code", None)
            if code == 404:
                return DetailResult(error="详情入口未命中，尝试搜索兜底")
            return DetailResult(status="unavailable", error="详情请求失败，请检查登录状态、网络或站点限流")
        if is_mteam(site):
            torrent = parse_mteam(response.json(), torrent_id)
            if torrent is None:
                return DetailResult(status="unavailable", error="详情接口未返回对应 ID，请检查权限或种子状态")
            params = {"method": "post", "cookie": False, "params": {"id": torrent_id},
                      "header": {**headers, "User-Agent": ua}, "proxy": bool(site.get("proxy")), "result": "data"}
            encoded = base64.b64encode(json.dumps(params).encode()).decode()
            torrent.update(page_url=page, enclosure=f"[{encoded}]{api}genDlToken")
        else:
            if re.search(r'(?i)type\s*=\s*[\"\']password|cf-chl-|challenge-platform', response.text):
                return DetailResult(status="unavailable", error="详情页要求登录或验证，请检查站点登录状态")
            torrent = parse_nexus(response.text, page, torrent_id)
            if torrent is None:
                return DetailResult(error="详情页结构未识别，尝试搜索兜底")
        ready = torrent.get("seeders") is not None and torrent.get("downloadvolumefactor") is not None
        return DetailResult(torrent, "ready" if ready else "partial",
                            None if ready else "详情未提供完整做种人数或促销")
    except Exception:
        # 不能将带 Cookie/API Key/Passkey 的异常文本保存到任务或发送前端。
        return DetailResult(status="unavailable", error="详情获取异常，请检查站点连接或响应格式")

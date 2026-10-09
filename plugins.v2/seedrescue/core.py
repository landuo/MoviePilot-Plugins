"""SeedRescue 中不依赖 MoviePilot 宿主的纯业务逻辑。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence
from urllib.parse import parse_qs, parse_qsl, urlencode, unquote, urlparse, urlunparse


FREE = "free"
NON_FREE = "non_free"
UNKNOWN = "unknown"
ALLOWED_PROMOTIONS = {FREE, NON_FREE}
SENSITIVE_URL_KEYS = {
    "apikey", "auth", "authkey", "key", "passkey", "rsskey", "token", "torrent_pass"
}


class TorrentFormatError(ValueError):
    """种子元数据不是有效的 bencode 数据。"""


@dataclass(frozen=True)
class IyuuMatch:
    """IYUU 返回的一条跨站种子映射。"""

    sid: Any
    torrent_id: str
    info_hash: str


@dataclass(frozen=True)
class SourceCandidate:
    """IYUU 已知来源，详情尚未取回的候选同样保留。"""

    match: IyuuMatch
    site_id: int
    site_name: str
    seeders: Optional[int]
    download_factor: Optional[float]
    priority: int
    torrent: Any = None
    metadata_status: str = "ready"
    metadata_error: Optional[str] = None
    lookup_method: Optional[str] = None


def _read_bytes(data: bytes, offset: int) -> tuple[bytes, int]:
    colon = data.find(b":", offset)
    if colon < 0:
        raise TorrentFormatError("无效的字符串长度")
    try:
        length = int(data[offset:colon])
    except ValueError as err:
        raise TorrentFormatError("无效的字符串长度") from err
    start = colon + 1
    end = start + length
    if length < 0 or end > len(data):
        raise TorrentFormatError("字符串超出种子数据范围")
    return data[start:end], end


def _skip_value(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise TorrentFormatError("种子数据意外结束")
    token = data[offset:offset + 1]
    if token == b"i":
        end = data.find(b"e", offset + 1)
        if end < 0:
            raise TorrentFormatError("无效的整数")
        try:
            int(data[offset + 1:end])
        except ValueError as err:
            raise TorrentFormatError("无效的整数") from err
        return end + 1
    if token == b"l":
        offset += 1
        while offset < len(data) and data[offset:offset + 1] != b"e":
            offset = _skip_value(data, offset)
        if offset >= len(data):
            raise TorrentFormatError("列表没有结束标记")
        return offset + 1
    if token == b"d":
        offset += 1
        while offset < len(data) and data[offset:offset + 1] != b"e":
            _, offset = _read_bytes(data, offset)
            offset = _skip_value(data, offset)
        if offset >= len(data):
            raise TorrentFormatError("字典没有结束标记")
        return offset + 1
    if b"0" <= token <= b"9":
        _, offset = _read_bytes(data, offset)
        return offset
    raise TorrentFormatError("未知的 bencode 类型")


def info_hash_from_torrent(content: bytes) -> str:
    """直接对原始 ``info`` 字典切片计算 SHA1，避免重编码改变 Hash。"""

    if not isinstance(content, bytes) or not content.startswith(b"d"):
        raise TorrentFormatError("种子顶层必须是字典")
    offset = 1
    while offset < len(content) and content[offset:offset + 1] != b"e":
        key, offset = _read_bytes(content, offset)
        value_start = offset
        offset = _skip_value(content, offset)
        if key == b"info":
            return hashlib.sha1(content[value_start:offset]).hexdigest()
    raise TorrentFormatError("种子缺少 info 字典")


def promotion_kind(download_factor: Any) -> str:
    """将下载系数严格归并为免费或非免费。"""

    if download_factor is None or download_factor == "":
        return UNKNOWN
    try:
        factor = float(download_factor)
    except (TypeError, ValueError):
        return UNKNOWN
    if factor == 0:
        return FREE
    if factor > 0:
        return NON_FREE
    return UNKNOWN


def normalize_promotions(values: Iterable[str]) -> set[str]:
    """只保留插件支持的免费、非免费两个配置值。"""

    if isinstance(values, str):
        values = [values]
    return {str(value) for value in values or [] if str(value) in ALLOWED_PROMOTIONS}


def iyuu_matches_for_hash(payload: Any, target_hash: str) -> list[IyuuMatch]:
    """从 IYUU 响应中提取指定目标 Hash 的跨站映射。"""

    if not isinstance(payload, dict) or not target_hash:
        return []
    seed_info = payload.get(target_hash)
    if seed_info is None:
        lowered = target_hash.lower()
        seed_info = next(
            (value for key, value in payload.items() if str(key).lower() == lowered),
            None,
        )
    if not isinstance(seed_info, dict):
        return []
    rows = seed_info.get("torrent")
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        return []
    matches: list[IyuuMatch] = []
    seen: set[tuple[Any, str, str]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("sid")
        torrent_id = row.get("torrent_id")
        info_hash = str(row.get("info_hash") or "").lower()
        if sid in (None, "") or torrent_id in (None, "") or len(info_hash) != 40:
            continue
        identity = (sid, str(torrent_id), info_hash)
        if identity in seen:
            continue
        seen.add(identity)
        matches.append(IyuuMatch(sid, str(torrent_id), info_hash))
    return matches


def extract_torrent_id(url: str) -> Optional[str]:
    """从常见详情页或下载地址中提取站点种子 ID。"""

    if not url:
        return None
    parsed = urlparse(unquote(str(url)))
    query = parse_qs(parsed.query)
    for key in ("id", "torrentid", "torrent_id", "tid"):
        values = query.get(key)
        if values and str(values[0]).isdigit():
            return str(values[0])
    path_parts = [part for part in parsed.path.split("/") if part]
    for part in reversed(path_parts):
        if part.isdigit():
            return part
    return None


def safe_page_url(url: Optional[str]) -> Optional[str]:
    """只保留可展示的 HTTP(S) 详情链接，并移除常见站点密钥参数。"""

    if not url:
        return None
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    query = urlencode([
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in SENSITIVE_URL_KEYS
    ])
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        query,
        "",
    ))


def search_keywords(title: str) -> list[str]:
    """优先使用媒体名和季度/年份，避开编码、音轨及发布组的命名差异。"""

    title = str(title or "").strip()
    if not title:
        return []
    values = []
    prefix = re.split(
        r"(?i)(?:[\s._-]+)(?:19\d{2}|20\d{2}|S\d{1,2}(?:E\d{1,3})?)(?=[\s._-]|$)",
        title,
        maxsplit=1,
    )[0]
    normalized = re.sub(r"[._-]+", " ", prefix).strip()
    if len(normalized) >= 2 and normalized.casefold() != title.casefold():
        season = re.search(r"(?i)(?:^|[\s._-])(S\d{1,2})(?:E\d{1,3})?(?=[\s._-]|$)", title)
        year = re.search(r"(?:^|[\s._-])((?:19|20)\d{2})(?=[\s._-]|$)", title)
        if season or year:
            values.append(f"{normalized} {(season or year).group(1).upper()}")
        values.append(normalized)
    values.append(title)
    return list(dict.fromkeys(values))


def ranked_sources(
    candidates: Sequence[SourceCandidate],
    minimum_seeders: Optional[int],
    allowed_promotions: Iterable[str],
) -> list[SourceCandidate]:
    """仅在设置人数门槛时过滤未知或不足的来源，促销筛选始终保留。"""

    allowed = normalize_promotions(allowed_promotions)
    if not allowed:
        return []
    eligible = [
        candidate
        for candidate in candidates
        if candidate.metadata_status == "ready"
        and (minimum_seeders is None or (
            candidate.seeders is not None and candidate.seeders >= minimum_seeders
        ))
        and promotion_kind(candidate.download_factor) in allowed
    ]
    return sorted(
        eligible,
        key=lambda item: (
            -int(item.seeders or 0),
            0 if promotion_kind(item.download_factor) == FREE else 1,
            item.priority,
        ),
    )


def torrent_is_complete(torrent: Any) -> bool:
    """严格判断数据完整；校验中、错误、缺失文件均不能视作已完成。"""

    if torrent is None:
        return False

    state = str(torrent_field(torrent, "state") or "").lower()
    if state.startswith("checking") or state in {"error", "missingfiles", "unknown"}:
        return False
    remaining = torrent_field(torrent, "amount_left")
    if remaining is not None:
        try:
            if float(remaining) != 0:
                return False
        except (TypeError, ValueError):
            return False
    progress = torrent_field(torrent, "progress")
    if progress is not None:
        try:
            return float(progress) in {1.0, 100.0}
        except (TypeError, ValueError):
            return False
    return state in {"uploading", "stalledup", "forcedup", "seeding"}


def torrent_field(torrent: Any, name: str) -> Any:
    return torrent.get(name) if isinstance(torrent, dict) else getattr(torrent, name, None)


def target_torrent_status(torrent: Any) -> tuple[str, Optional[str]]:
    """数据完整不等于正在做种；不主动恢复暂停任务或忽略校验。"""

    state = str(torrent_field(torrent, "state") or "").lower()
    if state.startswith("checking"):
        return "TARGET_RECHECKING", "目标种正在校验"
    if state in {"error", "missingfiles", "unknown"}:
        return "TARGET_ERROR", "目标种存在下载器错误或文件缺失，请在 qBittorrent 检查"
    if state.startswith(("paused", "stopped")):
        return "TARGET_PAUSED", "目标种已暂停，不会自动恢复"
    if torrent_is_complete(torrent):
        if state in {"uploading", "stalledup", "forcedup", "seeding"}:
            return "TARGET_SEEDING", None
        return "TARGET_COMPLETE", "数据已完整，等待下载器进入做种状态"
    return "TARGET_DOWNLOADING", None


def feed_key(enclosure: str, link: str, title: str) -> str:
    """生成不泄露 RSS Passkey 的稳定条目标识。"""

    raw = enclosure or link or title
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()

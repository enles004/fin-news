"""Feed fetching and parsing module."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import email.utils
import gzip
import html
import http.cookiejar
from pathlib import Path
import re
from typing import Any, Optional, Tuple
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from .health import SourceHealth
from .models import Article, article_id


class FetchError(Exception):
    """Raised when URL fetch fails after retries."""
    pass


def _parse_tz(tz_str: str) -> timezone:
    """Parse timezone string like '+07:00' or '+0700'."""
    m = re.match(r'([+-])(\d{2}):?(\d{2})?', tz_str)
    if m:
        sign = 1 if m.group(1) == '+' else -1
        hours = int(m.group(2))
        minutes = int(m.group(3)) if m.group(3) else 0
        return timezone(timedelta(minutes=sign * (hours * 60 + minutes)))
    return timezone(timedelta(hours=7))


def parse_date(s: Optional[str], default_tz: str = "+07:00") -> Optional[str]:
    """Parse various date formats to ISO 8601 string, or None if invalid."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None

    tz_default = _parse_tz(default_tz)

    # 1. Try ISO 8601 format
    try:
        iso_str = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz_default)
        return dt.isoformat()
    except Exception:
        pass

    # 2. Fix 2-digit year and missing minutes in timezone before RFC 2822
    fixed_s = s
    # e.g. "Tue, 03 Nov 26 11:38:28 +0700" -> replace " 26 " with " 2026 "
    fixed_s = re.sub(r'(\b\d{1,2}\s+[A-Za-z]{3}\s+)(\d{2})(\s+)', r'\g<1>20\2\3', fixed_s)
    # e.g. "+07" -> "+0700"
    fixed_s = re.sub(r'([+-]\d{2})$', r'\g<1>00', fixed_s)

    try:
        dt = email.utils.parsedate_to_datetime(fixed_s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz_default)
            return dt.isoformat()
    except Exception:
        pass

    # 3. Try custom formats like "11/3/2026 10:11:00 AM" or "%m/%d/%Y %I:%M:%S %p"
    custom_formats = [
        "%m/%d/%Y %I:%M:%S %p",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in custom_formats:
        try:
            dt = datetime.strptime(s, fmt)
            dt = dt.replace(tzinfo=tz_default)
            return dt.isoformat()
        except Exception:
            continue

    return None


_DEFAULT_OPENER = None


def fetch_url(url: str, *, timeout: int = 20, retries: int = 1, opener=None, cookie: Optional[str] = None) -> bytes:
    """Fetch URL, decompress gzip if needed, solve cookie challenges, retry on failure."""
    if opener is None:
        opener = _DEFAULT_OPENER
    cookie_header = cookie
    last_err = None

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                }
            )
            if cookie_header:
                req.add_header("Cookie", cookie_header)

            if opener is not None:
                resp = opener.open(req, timeout=timeout)
                data = resp.read()
            else:
                cj = http.cookiejar.CookieJar()
                active_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
                with active_opener.open(req, timeout=timeout) as resp:
                    data = resp.read()

            # Check if gzip-compressed (magic bytes 1f 8b)
            if len(data) >= 2 and data[:2] == b'\x1f\x8b':
                data = gzip.decompress(data)

            # Check for Lao Động / client-side JS cookie challenge
            # e.g. document.cookie="D1N=..."+"; expires=...; path=/"; window.location.reload(true);
            if b"document.cookie" in data and b"window.location.reload" in data:
                text = data.decode("utf-8", errors="ignore")
                m = re.search(r'document\.cookie\s*=\s*["\']([^=;\s"\']+)=([^;]+)', text)
                if m:
                    cookie_name = m.group(1).strip()
                    raw_val = m.group(2).strip()
                    cookie_val = re.sub(r'["\'\+\s]', '', raw_val.split(";")[0])
                    cookie_header = f"{cookie_name}={cookie_val}"
                    # Re-fetch with this cookie
                    continue

            return data
        except Exception as e:
            last_err = e

    raise FetchError(f"Failed to fetch {url} after {retries + 1} attempts: {last_err}")


def _strip_html(raw: str) -> str:
    """Strip HTML tags and unescape HTML entities."""
    if not raw:
        return ""
    # Strip HTML tags
    clean = re.sub(r'<[^>]+>', ' ', raw)
    # Unescape HTML entities
    clean = html.unescape(clean)
    # Normalize whitespace
    return " ".join(clean.split()).strip()


def parse_feed(xml_data: bytes, source_id: str, group: str) -> list[Article]:
    """Parse RSS or Atom XML bytes into Article list, stripping HTML/CDATA and tolerating BOM."""
    if not xml_data:
        return []

    # Strip BOM if present
    if xml_data.startswith(b'\xef\xbb\xbf'):
        xml_data = xml_data[3:]
    elif xml_data.startswith(b'\xff\xfe') or xml_data.startswith(b'\xfe\xff'):
        xml_data = xml_data.decode("utf-16").encode("utf-8")

    root = ET.fromstring(xml_data)
    articles = []
    fetched_at = datetime.now(timezone.utc).isoformat()

    # RSS 2.0 / 0.9 / 1.0 items
    items = root.findall(".//item")
    if not items:
        # Atom entries
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        if not items:
            items = root.findall(".//entry")

    for item in items:
        # Title
        title_el = item.find("title")
        if title_el is None:
            title_el = item.find("{http://www.w3.org/2005/Atom}title")
        title_raw = title_el.text if title_el is not None and title_el.text else ""
        title = _strip_html(title_raw)

        # Link
        url = ""
        link_el = item.find("link")
        if link_el is None:
            link_el = item.find("{http://www.w3.org/2005/Atom}link")
        if link_el is not None:
            if link_el.text and link_el.text.strip():
                url = link_el.text.strip()
            elif "href" in link_el.attrib:
                url = link_el.attrib["href"].strip()

        if not url:
            # Fallback to guid if it's a URL
            guid_el = item.find("guid")
            if guid_el is not None and guid_el.text and guid_el.text.startswith("http"):
                url = guid_el.text.strip()

        if not url:
            continue

        # Summary / description
        summary_raw = ""
        for tag in ["description", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content", "content"]:
            desc_el = item.find(tag)
            if desc_el is not None and desc_el.text:
                summary_raw = _strip_html(desc_el.text)
                break

        # Publication date
        pub_raw = None
        for tag in ["pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated", "{http://purl.org/dc/elements/1.1/}date"]:
            date_el = item.find(tag)
            if date_el is not None and date_el.text:
                pub_raw = date_el.text.strip()
                break

        published_at = parse_date(pub_raw) if pub_raw else None
        art_id = article_id(url)

        articles.append(Article(
            id=art_id,
            source=source_id,
            source_group=group,
            url=url,
            title=title,
            summary_raw=summary_raw,
            published_at=published_at,
            fetched_at=fetched_at,
            fulltext=None,
        ))

    return articles


def fetch_source(
    source_id: str,
    cfg: dict,
    *,
    limit: int = 10,
    since: Optional[datetime] = None,
    opener=None
) -> Tuple[list[Article], SourceHealth]:
    """Fetch articles for a single source, splitting limit across feeds, newest first."""
    checked_at = datetime.now(timezone.utc).isoformat()
    raw_url = cfg.get("url", [])
    urls = [raw_url] if isinstance(raw_url, str) else list(raw_url)
    group = cfg.get("group", "general")

    if not urls:
        return [], SourceHealth(source_id=source_id, status="empty", detail="no URLs configured", checked_at=checked_at)

    num_feeds = len(urls)
    all_articles = []
    feed_errors = []

    for i, url in enumerate(urls):
        feed_limit = limit // num_feeds + (1 if i < (limit % num_feeds) else 0)
        feed_limit = max(1, feed_limit)

        try:
            body = fetch_url(url, timeout=20, retries=1, opener=opener)
            parsed = parse_feed(body, source_id, group)

            # Filter by since if specified
            if since is not None:
                filtered = []
                for a in parsed:
                    if a.published_at:
                        try:
                            dt = datetime.fromisoformat(a.published_at)
                            if dt < since:
                                continue
                        except Exception:
                            pass
                    filtered.append(a)
                parsed = filtered

            # Sort newest first
            parsed.sort(key=lambda a: a.published_at or "", reverse=True)
            all_articles.extend(parsed[:feed_limit])
        except Exception as e:
            feed_errors.append(f"{url}: {e}")

    if len(feed_errors) == num_feeds:
        # All feeds failed
        return [], SourceHealth(
            source_id=source_id,
            status="error",
            detail="; ".join(feed_errors),
            checked_at=checked_at
        )

    if not all_articles:
        return [], SourceHealth(
            source_id=source_id,
            status="empty",
            detail="no articles found",
            checked_at=checked_at
        )

    # Sort combined results newest first and cap to limit
    all_articles.sort(key=lambda a: a.published_at or "", reverse=True)
    all_articles = all_articles[:limit]

    return all_articles, SourceHealth(
        source_id=source_id,
        status="ok",
        detail=f"{len(all_articles)} articles",
        checked_at=checked_at
    )


def fetch_all(
    sources_cfg: dict,
    *,
    limit: int = 10,
    groups: Optional[Any] = None,
    only: Optional[Any] = None,
    since: Optional[datetime] = None,
    opener=None
) -> Tuple[list[Article], list[SourceHealth]]:
    """Fetch articles from all enabled sources concurrently."""
    sources = sources_cfg.get("sources", sources_cfg)

    targets = {}
    for sid, scfg in sources.items():
        if not scfg.get("enabled", True):
            continue
        if groups is not None:
            target_groups = set(groups) if isinstance(groups, (list, set, tuple)) else {groups}
            if scfg.get("group") not in target_groups:
                continue
        if only is not None:
            target_only = set(only) if isinstance(only, (list, set, tuple)) else {only}
            if sid not in target_only:
                continue
        targets[sid] = scfg

    all_articles = []
    all_healths = []

    if not targets:
        return all_articles, all_healths

    max_workers = min(16, len(targets))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sid = {
            executor.submit(fetch_source, sid, scfg, limit=limit, since=since, opener=opener): sid
            for sid, scfg in targets.items()
        }
        for future in as_completed(future_to_sid):
            sid = future_to_sid[future]
            try:
                articles, health = future.result()
                all_articles.extend(articles)
                all_healths.append(health)
            except Exception as e:
                all_healths.append(SourceHealth(
                    source_id=sid,
                    status="error",
                    detail=str(e),
                    checked_at=datetime.now(timezone.utc).isoformat()
                ))

    return all_articles, all_healths

"""Data models for Fin-News."""
from dataclasses import dataclass
import hashlib
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode


def canonical_url(url: str) -> str:
    """Normalize URL by lowercasing host, removing tracking params, fragments, trailing slash."""
    if not url:
        return ""
    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if not path and parsed.path == "/":
        path = ""

    # Drop tracking query params: utm_*, fbclid, gclid, zarsrc
    tracking_prefixes = ("utm_",)
    tracking_exact = {"fbclid", "gclid", "zarsrc"}
    clean_params = []
    for k, v in parse_qsl(parsed.query, keep_blank_values=True):
        k_lower = k.lower()
        if any(k_lower.startswith(p) for p in tracking_prefixes) or k_lower in tracking_exact:
            continue
        clean_params.append((k, v))

    clean_query = urlencode(clean_params)
    return urlunparse((parsed.scheme.lower(), netloc, path, parsed.params, clean_query, ""))


def article_id(url: str) -> str:
    """Compute 12-char SHA-1 hash of canonical URL."""
    can = canonical_url(url)
    return hashlib.sha1(can.encode("utf-8")).hexdigest()[:12]


@dataclass
class Article:
    id: str
    source: str
    source_group: str
    url: str
    title: str
    summary_raw: str
    published_at: Optional[str]  # ISO8601
    fetched_at: str             # ISO8601
    fulltext: Optional[str] = None

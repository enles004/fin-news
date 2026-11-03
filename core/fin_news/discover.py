"""Feed discovery, testing, and adding module."""
from html.parser import HTMLParser
from typing import Any, List, Optional
from urllib.parse import urljoin, urlparse

from . import config
from . import fetch
from .health import SourceHealth


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feed_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]):
        if tag.lower() == "link":
            attr_dict = {k.lower(): (v or "") for k, v in attrs}
            rel = attr_dict.get("rel", "").lower()
            link_type = attr_dict.get("type", "").lower()
            href = attr_dict.get("href", "")
            if "alternate" in rel and ("rss" in link_type or "atom" in link_type or "xml" in link_type):
                if href:
                    self.feed_links.append(href.strip())


def discover_feeds(page_url: str, *, opener=None) -> List[str]:
    """Discover RSS/Atom feeds from <link rel='alternate'> and common paths."""
    candidates = []

    # 1. Fetch page and inspect <link> tags
    try:
        body = fetch.fetch_url(page_url, timeout=10, retries=1, opener=opener)
        text = body.decode("utf-8", errors="ignore")
        parser = LinkParser()
        parser.feed(text)
        for href in parser.feed_links:
            resolved = urljoin(page_url, href)
            if resolved not in candidates:
                candidates.append(resolved)
    except Exception:
        pass

    # 2. Add common paths if needed
    common_paths = ["/rss", "/feed", "/rss.xml", "/rss/home.rss"]
    parsed_page = urlparse(page_url)
    base_url = f"{parsed_page.scheme}://{parsed_page.netloc}"
    for p in common_paths:
        common_url = urljoin(base_url, p)
        if common_url not in candidates:
            candidates.append(common_url)

    # 3. Validate each candidate by verifying parse_feed returns >= 1 article
    valid_feeds = []
    for cand in candidates:
        try:
            cand_body = fetch.fetch_url(cand, timeout=10, retries=1, opener=opener)
            articles = fetch.parse_feed(cand_body, "test", "test")
            if len(articles) >= 1:
                valid_feeds.append(cand)
        except Exception:
            continue

    return valid_feeds


def add_source(
    page_url: str,
    *,
    source_id: Optional[str] = None,
    group: str = "general",
    opener=None
) -> dict:
    """Discover feeds from page URL and add to sources configuration."""
    feeds = discover_feeds(page_url, opener=opener)
    if not feeds:
        return {"found": False, "hint": "scrape"}

    if not source_id:
        domain = urlparse(page_url).netloc
        parts = domain.split(".")
        source_id = parts[0] if parts[0] != "www" or len(parts) < 2 else parts[1]

    # Sample titles from first feed
    sample_titles = []
    try:
        sample_body = fetch.fetch_url(feeds[0], timeout=10, retries=1, opener=opener)
        arts = fetch.parse_feed(sample_body, source_id, group)
        sample_titles = [a.title for a in arts[:3]]
    except Exception:
        pass

    feed_url_cfg = feeds if len(feeds) > 1 else feeds[0]
    new_cfg = {
        "url": feed_url_cfg,
        "kind": "rss",
        "group": group,
        "enabled": True,
        "cookie": False,
        "mixed": False,
    }
    config.set_value("sources", f"sources.{source_id}", new_cfg)

    return {
        "source_id": source_id,
        "feed_urls": feeds,
        "sample_titles": sample_titles,
    }


def test_source(source_id: str, cfg: dict, *, opener=None) -> SourceHealth:
    """Test a source configuration and return SourceHealth."""
    _, health = fetch.fetch_source(source_id, cfg, limit=5, opener=opener)
    return health

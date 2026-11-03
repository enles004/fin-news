"""Deduplication and topic pre-filtering module."""
import difflib
from typing import Any, List, Set
import unicodedata

from .models import Article, canonical_url


def strip_accents(text: str) -> str:
    """Normalize and strip Vietnamese diacritics/accents."""
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _is_earlier(a1: Article, a2: Article) -> bool:
    """Return True if a1 was published earlier than a2."""
    if a1.published_at and a2.published_at:
        return a1.published_at <= a2.published_at
    if a1.published_at and not a2.published_at:
        return True
    return False


def dedupe(articles: List[Article], threshold: float = 0.88) -> List[Article]:
    """Deduplicate articles by exact canonical URL then title similarity, keeping earliest published."""
    if not articles:
        return []

    # 1. Dedupe by canonical URL first
    by_url: dict[str, Article] = {}
    url_order: list[str] = []
    for art in articles:
        can_url = canonical_url(art.url)
        if can_url not in by_url:
            by_url[can_url] = art
            url_order.append(can_url)
        else:
            if _is_earlier(art, by_url[can_url]):
                by_url[can_url] = art

    unique_by_url = [by_url[u] for u in url_order]

    # 2. Dedupe by accent-stripped, case-folded title similarity
    clusters: list[list[Article]] = []
    norm_titles: list[str] = []

    for art in unique_by_url:
        norm_t = " ".join(strip_accents(art.title.lower()).split())
        matched = False
        for idx, rep_norm in enumerate(norm_titles):
            ratio = difflib.SequenceMatcher(None, norm_t, rep_norm).ratio()
            if ratio >= threshold:
                clusters[idx].append(art)
                matched = True
                break
        if not matched:
            clusters.append([art])
            norm_titles.append(norm_t)

    # For each cluster, pick the earliest published
    result = []
    for cluster in clusters:
        best = cluster[0]
        for candidate in cluster[1:]:
            if _is_earlier(candidate, best):
                best = candidate
        result.append(best)

    return result


def prefilter(articles: List[Article], topics_cfg: dict, mixed_sources: Set[str]) -> List[Article]:
    """Filter articles from mixed sources by topic keywords; other sources pass untouched."""
    topics = topics_cfg.get("topics", topics_cfg)
    keywords = []
    for topic_data in topics.values():
        if isinstance(topic_data, dict):
            keywords.extend(topic_data.get("keywords", []))
        elif isinstance(topic_data, list):
            keywords.extend(topic_data)

    norm_keywords = [
        " ".join(strip_accents(kw.lower()).split())
        for kw in keywords
        if kw
    ]

    result = []
    for art in articles:
        if art.source not in mixed_sources:
            result.append(art)
            continue

        text_to_check = f"{art.title} {art.summary_raw}"
        norm_text = " ".join(strip_accents(text_to_check.lower()).split())
        if any(kw in norm_text for kw in norm_keywords):
            result.append(art)

    return result

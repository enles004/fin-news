"""Live full-text extraction health checker and hint resolver."""
from typing import Any, Dict, Optional, Tuple

from . import config
from . import extract
from . import fetch


def get_effective_hints(
    source_id: str,
    cfg: Optional[dict] = None,
    profile: Optional[dict] = None
) -> Tuple[str, ...]:
    """Return effective body container hints merged from source config and global profile."""
    if profile is None:
        profile = config.load("profile")
    global_hints = profile.get("body_hints", []) or []

    source_hints = []
    if cfg is None:
        cfg = config.load("sources")
    if isinstance(cfg, dict):
        if "sources" in cfg and source_id in cfg["sources"]:
            source_hints = cfg["sources"][source_id].get("body_hints", []) or []
        elif source_id in cfg:
            source_hints = cfg[source_id].get("body_hints", []) or []
        elif "body_hints" in cfg:
            source_hints = cfg.get("body_hints", []) or []

    seen = set()
    merged = []
    for h in list(source_hints) + list(global_hints):
        if h and h not in seen:
            seen.add(h)
            merged.append(h)
    return tuple(merged)


STATUS_RANK = {
    "full": 4,
    "degraded": 3,
    "summary_only": 2,
    "error": 1,
}


def check_source(
    source_id: str,
    cfg: dict,
    profile: dict,
    *,
    opener=None
) -> dict:
    """Check live full-text extraction for a source by sampling up to 3 newest articles."""
    articles, health_obj = fetch.fetch_source(source_id, cfg, limit=10, opener=opener)
    seen_urls = set()
    distinct_articles = []
    for a in articles:
        if a.url and a.url not in seen_urls:
            seen_urls.add(a.url)
            distinct_articles.append(a)
            if len(distinct_articles) >= 3:
                break

    if health_obj.status != "ok" or not distinct_articles:
        return {
            "source": source_id,
            "status": "error",
            "tier": "",
            "chars": 0,
            "url": "",
            "error": health_obj.detail or "Không tìm thấy bài viết trong feed",
            "text": "",
        }

    hints = get_effective_hints(source_id, cfg, profile)
    max_chars = profile.get("fulltext_max_chars", 3500)

    best_result = None

    for art in distinct_articles:
        try:
            raw_bytes = fetch.fetch_url(art.url, timeout=10, retries=1, opener=opener)
            html = raw_bytes.decode("utf-8", errors="ignore")
            text, tier = extract.extract_with_tier(html, title=art.title, max_chars=max_chars, hints=hints)
            chars = len(text)

            if tier in ("json-ld", "article", "hint") and chars >= 300:
                status = "full"
            elif tier == "density" and chars >= 300:
                status = "degraded"
            else:
                status = "summary_only"

            current_res = {
                "source": source_id,
                "status": status,
                "tier": tier,
                "chars": chars,
                "url": art.url,
                "error": "",
                "text": text,
            }
        except Exception as e:
            current_res = {
                "source": source_id,
                "status": "error",
                "tier": "",
                "chars": 0,
                "url": art.url,
                "error": str(e),
                "text": "",
            }

        if best_result is None or STATUS_RANK.get(current_res["status"], 0) > STATUS_RANK.get(best_result["status"], 0):
            best_result = current_res
            if best_result["status"] == "full":
                break

    return best_result or {
        "source": source_id,
        "status": "error",
        "tier": "",
        "chars": 0,
        "url": "",
        "error": "Không có kết quả kiểm tra bài viết",
        "text": "",
    }

"""Source health monitoring, persistence, and reporting."""
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import List, Optional

from . import config


@dataclass
class SourceHealth:
    source_id: str
    status: str  # "ok" | "empty" | "error"
    detail: str
    checked_at: str  # ISO8601
    since: Optional[str] = None


def _health_file() -> Path:
    return config.home() / "data" / "health.json"


def _fulltext_health_file() -> Path:
    return config.home() / "data" / "fulltext-health.json"


def record(healths: List[SourceHealth], date_str: Optional[str] = None) -> None:
    """Persist last-ok and feed problem streak per source to <home>/data/health.json."""
    today = date_str or datetime.now().strftime("%Y-%m-%d")
    h_file = _health_file()
    h_file.parent.mkdir(parents=True, exist_ok=True)

    data = {}
    if h_file.exists():
        try:
            with open(h_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    last_ok = data.get("last_ok", {})
    feed_health = data.get("feed_health", {})

    for h in healths:
        prev = feed_health.get(h.source_id, {})
        prev_since = prev.get("since")
        if h.status == "ok":
            last_ok[h.source_id] = h.checked_at
            feed_health[h.source_id] = {
                "status": "ok",
                "last_checked": today,
                "since": None,
            }
        else:
            new_since = prev_since if (prev.get("status") in ("error", "empty") and prev_since) else today
            feed_health[h.source_id] = {
                "status": h.status,
                "last_checked": today,
                "since": new_since,
            }

    data["last_ok"] = last_ok
    data["feed_health"] = feed_health
    with open(h_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_fulltext_health() -> dict:
    """Load persisted fulltext health status from data/fulltext-health.json."""
    fh_file = _fulltext_health_file()
    if fh_file.exists():
        try:
            with open(fh_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def record_fulltext_health(results: List[dict], date_str: Optional[str] = None) -> None:
    """Persist fulltext health status with non-full streaks and resets."""
    today = date_str or datetime.now().strftime("%Y-%m-%d")
    data = load_fulltext_health()

    for res in results:
        sid = res.get("source", "")
        if not sid:
            continue
        status = res.get("status", "summary_only")
        tier = res.get("tier", "")
        prev = data.get(sid, {})
        prev_since = prev.get("since")
        prev_last_full = prev.get("last_full")

        if status == "full":
            new_since = None
            new_last_full = today
        else:
            new_since = prev_since if prev_since else today
            new_last_full = prev_last_full

        data[sid] = {
            "status": status,
            "tier": tier,
            "last_full": new_last_full,
            "last_checked": today,
            "since": new_since,
        }

    fh_file = _fulltext_health_file()
    fh_file.parent.mkdir(parents=True, exist_ok=True)
    with open(fh_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_source_health_problem_lines(healths: List[SourceHealth]) -> List[str]:
    """Return plain-Vietnamese lines for source connectivity failures."""
    failures = [h for h in healths if h.status != "ok"]
    if not failures:
        return []

    h_file = _health_file()
    last_ok = {}
    if h_file.exists():
        try:
            with open(h_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                last_ok = saved.get("last_ok", {})
        except Exception:
            pass

    lines = []
    for h in failures:
        raw_date = last_ok.get(h.source_id, h.checked_at)
        date_str = str(raw_date).split("T")[0] if raw_date else "chưa xác định"
        lines.append(f"- {h.source_id}: {h.detail} (lỗi từ {date_str})")
    return lines


def get_brief_problem_lines(
    healths: List[SourceHealth],
    sources_cfg: Optional[dict] = None,
    today_str: Optional[str] = None
) -> List[str]:
    """Return plain-Vietnamese lines for brief command problem block (feed problems only)."""
    failures = [h for h in healths if h.status in ("error", "empty")]
    if not failures:
        return []

    if sources_cfg is None:
        try:
            sources_cfg = config.load("sources").get("sources", {})
        except Exception:
            sources_cfg = {}

    today_date_str = today_str or datetime.now().strftime("%Y-%m-%d")
    try:
        today_date = datetime.strptime(today_date_str, "%Y-%m-%d").date()
    except Exception:
        today_date = datetime.now().date()

    # Load global feed health info if available
    h_file = _health_file()
    feed_health = {}
    if h_file.exists():
        try:
            with open(h_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                feed_health = saved.get("feed_health", {})
        except Exception:
            pass

    lines = []
    for h in failures:
        scfg = sources_cfg.get(h.source_id, {}) if isinstance(sources_cfg, dict) else {}
        label = scfg.get("label") or h.source_id

        if h.status == "error":
            desc = "hôm nay không đọc được"
        elif h.status == "empty":
            desc = "hôm nay không có bài mới"
        else:
            continue

        since_val = getattr(h, "since", None)
        if not since_val and h.source_id in feed_health:
            since_val = feed_health[h.source_id].get("since")

        if not since_val:
            data_dir = config.home() / "data"
            if data_dir.exists():
                curr = today_date - timedelta(days=1)
                earliest = None
                while True:
                    prev_dir = data_dir / curr.strftime("%Y-%m-%d")
                    prev_h_file = prev_dir / "health.json"
                    if prev_h_file.exists():
                        try:
                            with open(prev_h_file, "r", encoding="utf-8") as pf:
                                pdata = json.load(pf)
                            entry = next((item for item in pdata if item.get("source_id") == h.source_id), None)
                            if entry and entry.get("status") in ("error", "empty"):
                                earliest = curr
                                curr = curr - timedelta(days=1)
                                continue
                        except Exception:
                            pass
                    break
                if earliest:
                    since_val = earliest.strftime("%Y-%m-%d")

        since_suffix = ""
        if since_val:
            try:
                since_date_part = str(since_val).split("T")[0]
                since_dt = datetime.strptime(since_date_part, "%Y-%m-%d").date()
                if (today_date - since_dt).days >= 1:
                    since_suffix = f" (từ {since_dt.strftime('%d/%m')})"
            except Exception:
                pass

        lines.append(f"- {label}: {desc}{since_suffix}")

    return lines


def get_fulltext_problem_lines() -> List[str]:
    """Return plain-Vietnamese lines for full-text extraction failures/degradations."""
    data = load_fulltext_health()
    lines = []
    for sid, entry in data.items():
        status = entry.get("status")
        if status == "full":
            continue
        since = entry.get("since") or entry.get("last_checked") or "chưa xác định"
        tier = entry.get("tier", "")
        if status == "summary_only":
            lines.append(f"- {sid}: chỉ có tóm tắt RSS (từ {since})")
        elif status == "degraded":
            lines.append(f"- {sid}: trích xuất dự phòng (tầng {tier}, từ {since})")
        elif status == "error":
            lines.append(f"- {sid}: lỗi tải trang (từ {since})")
        else:
            lines.append(f"- {sid}: {status} (từ {since})")
    return lines


def render(healths: Optional[List[SourceHealth]] = None) -> str:
    """Render Vietnamese 'Sức khoẻ nguồn' and 'Toàn văn' blocks."""
    source_lines = get_source_health_problem_lines(healths or [])
    fulltext_lines = get_fulltext_problem_lines()

    if not source_lines and not fulltext_lines:
        return "Tất cả nguồn hoạt động bình thường."

    blocks = []
    if source_lines:
        blocks.append("### Sức khoẻ nguồn\n" + "\n".join(source_lines))
    if fulltext_lines:
        blocks.append("### Toàn văn\n" + "\n".join(fulltext_lines))

    return "\n\n".join(blocks)

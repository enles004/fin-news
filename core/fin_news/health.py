"""Source health monitoring, persistence, and reporting."""
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import List

from . import config


@dataclass
class SourceHealth:
    source_id: str
    status: str  # "ok" | "empty" | "error"
    detail: str
    checked_at: str  # ISO8601


def _health_file() -> Path:
    return config.home() / "data" / "health.json"


def record(healths: List[SourceHealth]) -> None:
    """Persist last-ok per source to <home>/data/health.json."""
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
    for h in healths:
        if h.status == "ok":
            last_ok[h.source_id] = h.checked_at

    data["last_ok"] = last_ok
    with open(h_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def render(healths: List[SourceHealth]) -> str:
    """Render Vietnamese 'Sức khoẻ nguồn' block."""
    failures = [h for h in healths if h.status != "ok"]
    if not failures:
        return "Tất cả nguồn hoạt động bình thường."

    # Load recorded last-ok dates
    h_file = _health_file()
    last_ok = {}
    if h_file.exists():
        try:
            with open(h_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                last_ok = saved.get("last_ok", {})
        except Exception:
            pass

    lines = ["### Sức khoẻ nguồn"]
    for h in failures:
        raw_date = last_ok.get(h.source_id, h.checked_at)
        date_str = str(raw_date).split("T")[0] if raw_date else "chưa xác định"
        lines.append(f"- {h.source_id}: {h.detail} (lỗi từ {date_str})")

    return "\n".join(lines)

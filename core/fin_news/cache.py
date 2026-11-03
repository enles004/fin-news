"""Persistent classification cache and step timing logging module."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config


def get_cache_file() -> Path:
    """Return Path to <FIN_NEWS_HOME>/cache/classified.json."""
    return config.home() / "cache" / "classified.json"


def load_cache() -> Dict[str, dict]:
    """Load classified cache if exists."""
    cache_file = get_cache_file()
    if not cache_file.exists():
        return {}
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for aid, entry in data.items():
                if isinstance(entry, dict) and "id" not in entry:
                    entry["id"] = aid
            return data
    except Exception:
        pass
    return {}


def update_and_prune_cache(valid_rows: List[dict], now: Optional[datetime] = None) -> None:
    """Write valid rows into cache and prune entries older than 7 days."""
    if now is None:
        now = datetime.now(timezone.utc)

    today_str = now.strftime("%Y-%m-%d")
    cutoff_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    cache = load_cache()

    # Prune entries older than 7 days
    pruned = {
        aid: entry
        for aid, entry in cache.items()
        if entry.get("date", "") >= cutoff_str
    }

    # Add new valid rows
    for row in valid_rows:
        aid = row.get("id")
        if aid:
            pruned[aid] = {
                "topics": row.get("topics", []),
                "importance": row.get("importance", 0),
                "is_noise": row.get("is_noise", False),
                "event_key": row.get("event_key", ""),
                "date": today_str,
            }

    cache_file = get_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)


def prune_cache(now: Optional[datetime] = None) -> int:
    """Prune cache entries older than 7 days without adding new entries."""
    if now is None:
        now = datetime.now(timezone.utc)
    cutoff_str = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    cache = load_cache()
    pruned = {
        aid: entry
        for aid, entry in cache.items()
        if entry.get("date", "") >= cutoff_str
    }
    dropped = len(cache) - len(pruned)
    cache_file = get_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(pruned, f, ensure_ascii=False, indent=2)
    return dropped


def log_step(step: str, duration: float, **kwargs) -> None:
    """Append step execution duration and details to logs/YYYY-MM-DD.log."""
    now = datetime.now()
    log_dir = config.home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{now.strftime('%Y-%m-%d')}.log"
    iso_time = now.isoformat()
    extra_str = " ".join(f"{k}={v}" for k, v in kwargs.items() if v is not None)
    line = f"{iso_time} step={step} seconds={duration:.1f} {extra_str}".strip() + "\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)


def get_last_run_stats() -> List[Tuple[str, float]]:
    """Return step timings from the latest log file."""
    log_dir = config.home() / "logs"
    if not log_dir.exists():
        return []

    log_files = sorted(log_dir.glob("*.log"), reverse=True)
    if not log_files:
        return []

    latest_log = log_files[0]
    lines = latest_log.read_text(encoding="utf-8").splitlines()
    steps = []
    for line in lines:
        parts = line.strip().split()
        step_name = None
        duration = 0.0
        for p in parts:
            if p.startswith("step="):
                step_name = p.split("=", 1)[1]
            elif p.startswith("seconds="):
                try:
                    duration = float(p.split("=", 1)[1])
                except Exception:
                    pass
        if step_name:
            steps.append((step_name, duration))

    return steps

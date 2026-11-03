"""File lock mechanism to prevent overlapping runs."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Iterator


@contextmanager
def acquire(path: Path, timeout: int = 0) -> Iterator[None]:
    """Acquire a file lock. Raise RuntimeError if active lock exists. Override stale lock (>2h)."""
    path = Path(path)
    if path.exists():
        try:
            mtime = path.stat().st_mtime
            age_seconds = time.time() - mtime
        except Exception:
            age_seconds = 0

        # Stale lock threshold: 2 hours (7200 seconds)
        if age_seconds > 7200:
            path.unlink(missing_ok=True)
        else:
            start_time = "unknown"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                start_time = data.get("start_time", "unknown")
            except Exception:
                pass
            raise RuntimeError(f"Another run is currently active (started at {start_time}). Exiting.")

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_info = {
        "pid": os.getpid(),
        "start_time": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(lock_info), encoding="utf-8")

    try:
        yield
    finally:
        path.unlink(missing_ok=True)

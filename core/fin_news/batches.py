"""Batch generation and System 1 result validation module."""
import json
from pathlib import Path
import re
from typing import Any, List, Optional, Set, Tuple

from . import config
from .models import Article


def truncate_at_word(text: Optional[str], max_chars: int, ellipsis: str = "") -> str:
    """Truncate text to max_chars at a word boundary, appending ellipsis if truncated."""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    target_len = max_chars - len(ellipsis) if ellipsis else max_chars
    if target_len <= 0:
        return ellipsis[:max_chars]
    truncated = text[:target_len]
    last_space = max(truncated.rfind(" "), truncated.rfind("\t"), truncated.rfind("\n"))
    if last_space > 0:
        return truncated[:last_space].rstrip() + ellipsis
    return truncated.rstrip() + ellipsis


def make_batches(
    articles: List[Article],
    size: int,
    out_dir: Path,
    lede_chars: int = 200
) -> List[Path]:
    """Split articles into JSON batch files of given size with prompt fields only, cutting summary_raw to lede_chars."""
    out_dir.mkdir(parents=True, exist_ok=True)
    batch_files = []

    for idx in range(0, len(articles), size):
        chunk = articles[idx:idx + size]
        batch_idx = idx // size + 1
        batch_path = out_dir / f"batch-{batch_idx:02d}.json"
        batch_data = [
            {
                "id": a.id,
                "source": a.source,
                "title": a.title,
                "summary_raw": truncate_at_word(a.summary_raw, lede_chars),
            }
            for a in chunk
        ]
        with open(batch_path, "w", encoding="utf-8") as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)
        batch_files.append(batch_path)

    return batch_files


def validate_lines(raw: str, expected_ids: List[str], topics: Set[str]) -> Tuple[List[dict], List[str]]:
    """Validate raw System 1 plain text lines output against expected ids and topics schema.

    Format: id|topic1,topic2|importance|noise|event_key
    """
    if not raw or not isinstance(raw, str) or not raw.strip():
        return [], list(expected_ids)

    expected_set = set(expected_ids)
    valid_rows: List[dict] = []
    seen_ids: Set[str] = set()
    problem_ids_set: Set[str] = set()
    unparseable = False

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines and expected_ids:
        return [], list(expected_ids)

    for line in lines:
        parts = line.split("|")
        if len(parts) != 5:
            if len(parts) > 0 and parts[0].strip() in expected_set:
                problem_ids_set.add(parts[0].strip())
            else:
                unparseable = True
            continue

        aid, topics_str, imp_str, noise_str, event_key = [p.strip() for p in parts]

        if aid not in expected_set:
            unparseable = True
            continue

        if aid in seen_ids:
            problem_ids_set.add(aid)
            continue

        seen_ids.add(aid)

        # Check noise: "0" or "1"
        if noise_str not in ("0", "1"):
            problem_ids_set.add(aid)
            continue
        is_noise = (noise_str == "1")

        # Check importance: integer 0-5
        if not (imp_str.isdigit() and 0 <= int(imp_str) <= 5):
            problem_ids_set.add(aid)
            continue
        importance = int(imp_str)

        # Check event_key: ^[a-z0-9-]{3,60}$
        if not re.match(r"^[a-z0-9-]{3,60}$", event_key):
            problem_ids_set.add(aid)
            continue

        # Check topics:
        if topics_str:
            topic_list = [t.strip() for t in topics_str.split(",") if t.strip()]
        else:
            topic_list = []

        if not topic_list:
            if not is_noise:
                problem_ids_set.add(aid)
                continue
        else:
            if not all(t in topics for t in topic_list):
                problem_ids_set.add(aid)
                continue

        valid_rows.append({
            "id": aid,
            "topics": topic_list,
            "importance": importance,
            "is_noise": is_noise,
            "event_key": event_key,
        })

    # Missing IDs
    for eid in expected_ids:
        if eid not in seen_ids:
            problem_ids_set.add(eid)

    if unparseable and not valid_rows:
        return [], list(expected_ids)

    valid_rows = [r for r in valid_rows if r["id"] not in problem_ids_set]
    ordered_problems = [eid for eid in expected_ids if eid in problem_ids_set]

    if unparseable:
        return [], list(expected_ids)

    return valid_rows, ordered_problems


def merge_results(batch_dir: Path, topics: Optional[Set[str]] = None) -> Tuple[List[dict], List[str]]:
    """Merge result-NN.txt files from batch directory and return valid rows and unresolved ids."""
    if topics is None:
        try:
            topics_data = config.load("topics").get("topics", {})
            topics = set(topics_data.keys())
        except Exception:
            topics = set()

    batch_files = sorted(batch_dir.glob("batch-*.json"))
    all_valid_rows = []
    unresolved_ids = []

    for b_path in batch_files:
        try:
            with open(b_path, "r", encoding="utf-8") as f:
                b_data = json.load(f)
            expected_ids = [item["id"] for item in b_data if isinstance(item, dict) and "id" in item]
        except Exception:
            continue

        r_path = batch_dir / b_path.name.replace("batch-", "result-").replace(".json", ".txt")
        if not r_path.exists():
            unresolved_ids.extend(expected_ids)
            continue

        try:
            with open(r_path, "r", encoding="utf-8") as f:
                raw = f.read()
            valid, problems = validate_lines(raw, expected_ids, topics)
            all_valid_rows.extend(valid)
            unresolved_ids.extend(problems)
        except Exception:
            unresolved_ids.extend(expected_ids)

    return all_valid_rows, unresolved_ids

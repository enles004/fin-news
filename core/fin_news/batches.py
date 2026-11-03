"""Batch generation and System 1 result validation module."""
import json
from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from . import config
from .models import Article


def make_batches(articles: List[Article], size: int, out_dir: Path) -> List[Path]:
    """Split articles into JSON batch files of given size with prompt fields only."""
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
                "summary_raw": a.summary_raw,
            }
            for a in chunk
        ]
        with open(batch_path, "w", encoding="utf-8") as f:
            json.dump(batch_data, f, ensure_ascii=False, indent=2)
        batch_files.append(batch_path)

    return batch_files


def validate_result(raw: str, expected_ids: List[str], topics: Set[str]) -> Tuple[List[dict], List[str]]:
    """Validate raw System 1 JSON output against expected ids and topics schema."""
    if not raw or not isinstance(raw, str):
        return [], list(expected_ids)

    try:
        data = json.loads(raw)
        if not isinstance(data, list):
            return [], list(expected_ids)
    except Exception:
        return [], list(expected_ids)

    expected_set = set(expected_ids)
    valid_rows = []
    seen_ids = set()
    problem_ids_set = set()

    for item in data:
        if not isinstance(item, dict):
            continue

        rid = item.get("id")
        if not rid or rid not in expected_set or rid in seen_ids:
            if rid and rid in expected_set:
                problem_ids_set.add(rid)
            continue

        # Check is_noise first as topics validation depends on it
        is_noise = item.get("is_noise")
        if not isinstance(is_noise, bool):
            problem_ids_set.add(rid)
            continue

        # Check topics: [] is valid only when is_noise is True; non-empty topics must be in allowed topics
        rtopics = item.get("topics")
        if not isinstance(rtopics, list):
            problem_ids_set.add(rid)
            continue

        if not rtopics:
            if not is_noise:
                problem_ids_set.add(rid)
                continue
        else:
            if not all(t in topics for t in rtopics):
                problem_ids_set.add(rid)
                continue

        # Check importance
        imp = item.get("importance")
        if not isinstance(imp, (int, float)) or imp < 0 or imp > 5:
            problem_ids_set.add(rid)
            continue

        # Check other required schema fields
        if not isinstance(item.get("summary_vi"), str):
            problem_ids_set.add(rid)
            continue
        if not isinstance(item.get("entities"), list):
            problem_ids_set.add(rid)
            continue
        if not isinstance(item.get("importance_reason"), str):
            problem_ids_set.add(rid)
            continue
        if not isinstance(item.get("event_key"), str):
            problem_ids_set.add(rid)
            continue

        seen_ids.add(rid)
        valid_rows.append(item)

    # Missing IDs
    for eid in expected_ids:
        if eid not in seen_ids:
            problem_ids_set.add(eid)

    ordered_problems = [eid for eid in expected_ids if eid in problem_ids_set]
    return valid_rows, ordered_problems


def merge_results(batch_dir: Path, topics: Optional[Set[str]] = None) -> Tuple[List[dict], List[str]]:
    """Merge result-NN.json files from batch directory and return valid rows and unresolved ids."""
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

        r_path = batch_dir / b_path.name.replace("batch-", "result-")
        if not r_path.exists():
            unresolved_ids.extend(expected_ids)
            continue

        try:
            with open(r_path, "r", encoding="utf-8") as f:
                raw = f.read()
            valid, problems = validate_result(raw, expected_ids, topics)
            all_valid_rows.extend(valid)
            unresolved_ids.extend(problems)
        except Exception:
            unresolved_ids.extend(expected_ids)

    return all_valid_rows, unresolved_ids

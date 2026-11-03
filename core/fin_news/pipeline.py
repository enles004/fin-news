"""Pipeline orchestration for fetch, prepare, collect, cluster, and fulltext."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, List, Optional, Tuple

from . import batches
from . import cluster
from . import config
from . import dedupe
from . import extract
from . import fetch
from . import health
from . import lock
from .health import SourceHealth
from .models import Article


def empty_day_notice(healths: List[SourceHealth]) -> str:
    """Format notice when zero articles survive after fetch/filter."""
    health_text = health.render(healths)
    return f"Hôm nay không có tin tức nào phù hợp (0 bài viết).\n\n{health_text}"


def get_today_dir(date_str: Optional[str] = None) -> Path:
    """Return Path to data/YYYY-MM-DD/ directory."""
    day = date_str or datetime.now().strftime("%Y-%m-%d")
    d = config.home() / "data" / day
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_fetch(
    *,
    groups: Optional[List[str]] = None,
    only: Optional[List[str]] = None,
    limit: Optional[int] = None,
    since_str: Optional[str] = None,
    query: Optional[str] = None,
    topics: Optional[List[str]] = None,
    opener=None
) -> int:
    """Execute fetch subcommand, saving raw.json and health.json under lock."""
    today_dir = get_today_dir()
    lock_file = today_dir / ".lock"

    with lock.acquire(lock_file):
        sources_cfg = config.load("sources")
        profile = config.load("profile")

        if query:
            fetch_limit = 1000
        elif limit is not None:
            fetch_limit = limit
        else:
            fetch_limit = profile.get("max_per_source", 10)

        # Parse since_str e.g. "7d"
        since_dt = None
        if since_str and since_str.endswith("d"):
            try:
                days = int(since_str[:-1])
                since_dt = datetime.now(timezone.utc) - (days * timedelta(days=1))
            except Exception:
                pass

        articles, healths = fetch.fetch_all(
            sources_cfg,
            limit=fetch_limit,
            groups=groups,
            only=only,
            since=since_dt,
            opener=opener
        )

        if query:
            q_clean = query.strip()
            articles = [
                a for a in articles
                if q_clean in a.title or q_clean in a.summary_raw
            ]

        # Write raw.json
        raw_path = today_dir / "raw.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in articles], f, ensure_ascii=False, indent=2)

        # Record health globally and save local health.json
        health.record(healths)
        health_path = today_dir / "health.json"
        with open(health_path, "w", encoding="utf-8") as f:
            json.dump([asdict(h) for h in healths], f, ensure_ascii=False, indent=2)

        if len(articles) == 0:
            print(empty_day_notice(healths))
        else:
            print(f"Đã tải {len(articles)} bài viết từ {len(healths)} nguồn.")

    return 0


def run_prepare() -> int:
    """Dedupe and prefilter raw articles, writing articles.json and batch files."""
    today_dir = get_today_dir()
    raw_path = today_dir / "raw.json"
    if not raw_path.exists():
        print("Lỗi: Không tìm thấy raw.json. Hãy chạy lệnh 'fetch' trước.")
        return 1

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    articles = [Article(**item) for item in raw_items]

    # Dedupe
    deduped = dedupe.dedupe(articles)

    # Prefilter mixed sources
    sources_cfg = config.load("sources").get("sources", {})
    mixed_sources = {sid for sid, scfg in sources_cfg.items() if scfg.get("mixed", False)}
    topics_cfg = config.load("topics")
    filtered = dedupe.prefilter(deduped, topics_cfg, mixed_sources)

    # Write articles.json
    articles_path = today_dir / "articles.json"
    with open(articles_path, "w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in filtered], f, ensure_ascii=False, indent=2)

    # Create batches
    profile = config.load("profile")
    batch_size = profile.get("batch_size", 25)
    batches_dir = today_dir / "batches"
    batch_files = batches.make_batches(filtered, batch_size, batches_dir)

    for bf in batch_files:
        print(str(bf))

    return 0


def run_collect() -> int:
    """Merge result-NN.json batches, return exit code 3 if any unresolved ids remain."""
    today_dir = get_today_dir()
    batches_dir = today_dir / "batches"
    if not batches_dir.exists():
        print("Lỗi: Không tìm thấy thư mục batches.")
        return 1

    topics_data = config.load("topics").get("topics", {})
    topics_set = set(topics_data.keys())
    valid_rows, problem_ids = batches.merge_results(batches_dir, topics=topics_set)

    if problem_ids:
        print(f"Cần chạy lại ({len(problem_ids)} bài): {', '.join(problem_ids)}")
        return 3

    print(f"Hoàn thành thu thập {len(valid_rows)} bài viết.")
    return 0


def run_cluster(skip_merge: bool = False) -> int:
    """Cluster classified articles, score them, and either prepare merge plan or save clusters.json directly."""
    today_dir = get_today_dir()
    articles_path = today_dir / "articles.json"
    if not articles_path.exists():
        print("Lỗi: Không tìm thấy articles.json.")
        return 1

    with open(articles_path, "r", encoding="utf-8") as f:
        art_items = json.load(f)
    articles = [Article(**item) for item in art_items]
    articles_by_id = {a.id: a for a in articles}

    batches_dir = today_dir / "batches"
    valid_rows, _ = batches.merge_results(batches_dir)
    classified_by_id = {r["id"]: r for r in valid_rows}

    clusters = cluster.cluster(articles, valid_rows)
    profile = config.load("profile")
    now = datetime.now(timezone.utc)

    for cl in clusters:
        cluster.score(cl, articles_by_id, classified_by_id, profile, now)

    if skip_merge:
        selected = cluster.select(clusters, profile)
        clusters_path = today_dir / "clusters.json"
        with open(clusters_path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in selected], f, ensure_ascii=False, indent=2)

        for c in selected:
            print(f"[{c.cluster_id}] (Score: {c.score:.2f}, {c.source_count} nguồn) {c.headline}")

        return 0

    # Write clusters-raw.json (all clusters)
    clusters_raw_path = today_dir / "clusters-raw.json"
    with open(clusters_raw_path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in clusters], f, ensure_ascii=False, indent=2)

    # Write merge-input.json (merge_plan output)
    plan = cluster.merge_plan(clusters, articles_by_id)
    merge_input_path = today_dir / "merge-input.json"
    with open(merge_input_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    print(f"Đã tạo clusters-raw.json ({len(clusters)} cụm) và merge-input.json.")
    print("Bước tiếp theo: Dispatch subagent cluster-merger để tạo merge-result.json, sau đó gọi 'merge'.")
    return 0


def run_merge() -> int:
    """Read merge-result.json, validate and apply merge, write clusters.json."""
    today_dir = get_today_dir()
    merge_result_path = today_dir / "merge-result.json"
    if not merge_result_path.exists():
        print("Lỗi: Không tìm thấy merge-result.json. Hãy dispatch subagent cluster-merger trước.")
        return 4

    clusters_raw_path = today_dir / "clusters-raw.json"
    articles_path = today_dir / "articles.json"
    if not clusters_raw_path.exists() or not articles_path.exists():
        print("Lỗi: Thiếu clusters-raw.json hoặc articles.json.")
        return 1

    with open(clusters_raw_path, "r", encoding="utf-8") as f:
        raw_cluster_items = json.load(f)
    clusters = [cluster.Cluster(**item) for item in raw_cluster_items]

    with open(articles_path, "r", encoding="utf-8") as f:
        art_items = json.load(f)
    articles = [Article(**item) for item in art_items]
    articles_by_id = {a.id: a for a in articles}

    batches_dir = today_dir / "batches"
    valid_rows, _ = batches.merge_results(batches_dir)
    classified_by_id = {r["id"]: r for r in valid_rows}

    profile = config.load("profile")
    now = datetime.now(timezone.utc)

    cluster_ids = [c.cluster_id for c in clusters]
    raw_text = merge_result_path.read_text(encoding="utf-8")
    valid_groups, problems = cluster.validate_merge(raw_text, cluster_ids)

    merged_clusters = cluster.apply_merge(
        clusters,
        valid_groups,
        articles_by_id,
        classified_by_id,
        profile,
        now
    )

    clusters_path = today_dir / "clusters.json"
    with open(clusters_path, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in merged_clusters], f, ensure_ascii=False, indent=2)

    for c in merged_clusters:
        print(f"[{c.cluster_id}] (Score: {c.score:.2f}, {c.source_count} nguồn) {c.headline}")

    if problems:
        for p in problems:
            print(f"Cảnh báo: {p}")
        return 3

    return 0


def run_fulltext(cluster_ids: List[str]) -> int:
    """Fetch article fulltext for specified cluster IDs."""
    today_dir = get_today_dir()
    clusters_path = today_dir / "clusters.json"
    articles_path = today_dir / "articles.json"
    if not clusters_path.exists() or not articles_path.exists():
        print("Lỗi: Thiếu clusters.json hoặc articles.json.")
        return 1

    with open(clusters_path, "r", encoding="utf-8") as f:
        clusters_data = json.load(f)
    with open(articles_path, "r", encoding="utf-8") as f:
        articles_data = json.load(f)

    articles_by_id = {a["id"]: a for a in articles_data}
    fulltext_dir = today_dir / "fulltext"
    fulltext_dir.mkdir(parents=True, exist_ok=True)

    profile = config.load("profile")
    max_per_cluster = profile.get("fulltext_articles_per_cluster", 2)
    max_chars = profile.get("fulltext_max_chars", 3500)

    batches_dir = today_dir / "batches"
    classified_by_id = {}
    if batches_dir.exists():
        try:
            valid_rows, _ = batches.merge_results(batches_dir)
            classified_by_id = {r["id"]: r for r in valid_rows}
        except Exception:
            classified_by_id = {}

    status_file = fulltext_dir / "_status.json"
    status_data = {}
    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            status_data = {}

    run_results: List[str] = []
    target_clusters = [c for c in clusters_data if c["cluster_id"] in cluster_ids]

    for cl in target_clusters:
        print(f"\n=== Cụm {cl['cluster_id']}: {cl['headline']} ===")

        # Collect articles in cluster with importance
        cluster_articles = []
        for aid in cl.get("article_ids", []):
            art = articles_by_id.get(aid)
            if art:
                imp = classified_by_id.get(aid, {}).get("importance", 0)
                cluster_articles.append((art, imp))

        # Sort descending by importance
        cluster_articles.sort(key=lambda item: item[1], reverse=True)

        # Select at most max_per_cluster, choosing distinct sources first
        selected_arts = []
        seen_sources = set()
        # Round 1: distinct sources, highest importance first
        for art, _ in cluster_articles:
            src = art.get("source", "")
            if src not in seen_sources:
                selected_arts.append(art)
                seen_sources.add(src)
                if len(selected_arts) >= max_per_cluster:
                    break

        # Round 2: fill remaining quota with remaining highest importance articles
        if len(selected_arts) < max_per_cluster:
            for art, _ in cluster_articles:
                if art not in selected_arts:
                    selected_arts.append(art)
                    if len(selected_arts) >= max_per_cluster:
                        break

        for art in selected_arts:
            aid = art["id"]
            src = art.get("source", "")
            title = art.get("title", "")
            summary_raw = art.get("summary_raw", "")
            txt_path = fulltext_dir / f"{aid}.txt"

            status = "summary_only"
            chars = 0
            error_msg = ""
            body_text = summary_raw

            try:
                raw_bytes = fetch.fetch_url(art["url"], timeout=10, retries=1)
                extracted = extract.extract_article_text(
                    raw_bytes.decode("utf-8", errors="ignore"),
                    title=title,
                    max_chars=max_chars
                )
                if extracted:
                    status = "full"
                    body_text = extracted
                    chars = len(body_text)
                else:
                    status = "summary_only"
                    body_text = summary_raw
                    chars = len(body_text)
            except Exception as e:
                status = "error"
                error_msg = str(e)
                body_text = summary_raw
                chars = len(body_text)

            txt_path.write_text(body_text, encoding="utf-8")

            status_entry = {
                "source": src,
                "status": status,
                "chars": chars,
                "error": error_msg,
            }
            status_data[aid] = status_entry
            run_results.append(status)

            label = "[toàn văn]" if status == "full" else "[chỉ có tóm tắt RSS]"
            if status == "error":
                print(f"- [{src}] {title} [lỗi tải trang: {error_msg}] {label}\n  {body_text[:300]}...\n")
            else:
                print(f"- [{src}] {title} {label}\n  {body_text[:300]}...\n")

    status_file.write_text(json.dumps(status_data, ensure_ascii=False, indent=2), encoding="utf-8")

    total_run = len(run_results)
    full_count = sum(1 for s in run_results if s == "full")
    summary_count = sum(1 for s in run_results if s == "summary_only")
    error_count = sum(1 for s in run_results if s == "error")
    print(f"Toàn văn: {full_count}/{total_run} bài; chỉ tóm tắt: {summary_count}; lỗi: {error_count}.")

    return 0

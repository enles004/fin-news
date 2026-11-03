"""Pipeline orchestration for fetch, prepare, collect, cluster, brief, finish, fulltext, and stats."""
from dataclasses import asdict
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from . import batches
from . import cache
from . import cluster
from . import config
from . import dedupe
from . import extract
from . import fetch
from . import fulltext_check
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
    opener=None,
    verbose: bool = False
) -> int:
    """Execute fetch subcommand, saving raw.json and health.json under lock."""
    t0 = time.time()
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

        duration = time.time() - t0
        cache.log_step("fetch", duration, articles=len(articles), sources=len(healths))

        if len(articles) == 0:
            print(empty_day_notice(healths))
        else:
            print(f"Đã tải {len(articles)} bài viết từ {len(healths)} nguồn.")

    return 0


def run_prepare(verbose: bool = False) -> int:
    """Dedupe, filter by max_age_hours, exclude cached, writing articles.json and batch files."""
    t0 = time.time()
    today_dir = get_today_dir()
    raw_path = today_dir / "raw.json"
    if not raw_path.exists():
        print("Lỗi: Không tìm thấy raw.json. Hãy chạy lệnh 'fetch' trước.")
        return 1

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    articles = [Article(**item) for item in raw_items]

    profile = config.load("profile")
    max_age_hours = profile.get("max_age_hours", 36)
    now = datetime.now(timezone.utc)

    # Filter out articles older than max_age_hours (keep articles without a date)
    age_filtered: List[Article] = []
    for a in articles:
        if a.published_at:
            try:
                dt = datetime.fromisoformat(a.published_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                age_hours = (now - dt).total_seconds() / 3600.0
                if age_hours > max_age_hours:
                    continue
            except Exception:
                pass
        age_filtered.append(a)

    # Dedupe
    deduped = dedupe.dedupe(age_filtered)

    # Prefilter mixed sources
    sources_cfg = config.load("sources").get("sources", {})
    mixed_sources = {sid for sid, scfg in sources_cfg.items() if scfg.get("mixed", False)}
    topics_cfg = config.load("topics")
    filtered = dedupe.prefilter(deduped, topics_cfg, mixed_sources)

    # Write articles.json containing all surviving current articles (new + cached)
    articles_path = today_dir / "articles.json"
    with open(articles_path, "w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in filtered], f, ensure_ascii=False, indent=2)

    # Check cache to exclude already classified articles from batches
    cached_data = cache.load_cache()
    cached_ids = set(cached_data.keys())
    to_classify = [a for a in filtered if a.id not in cached_ids]
    cached_count = len(filtered) - len(to_classify)

    batches_dir = today_dir / "batches"
    batch_files = []

    if not to_classify:
        # Clear existing batches if any
        if batches_dir.exists():
            for old_bf in batches_dir.glob("batch-*.json"):
                try:
                    old_bf.unlink()
                except Exception:
                    pass
        print(f"Đã chuẩn bị 0 bài viết mới (bỏ qua {cached_count} bài đã phân loại).")
        print("Không có bài viết mới cần phân loại.")
    else:
        batch_size = profile.get("batch_size", 70)
        lede_chars = profile.get("lede_chars", 200)
        batch_files = batches.make_batches(to_classify, batch_size, batches_dir, lede_chars=lede_chars)
        print(f"Đã chuẩn bị {len(to_classify)} bài viết mới (bỏ qua {cached_count} bài đã phân loại).")
        for bf in batch_files:
            print(str(bf))

    duration = time.time() - t0
    cache.log_step("prepare", duration, batches=len(batch_files), cached=cached_count, new=len(to_classify))
    return 0


def run_collect(verbose: bool = False) -> int:
    """Merge result-NN.txt batches, update cache, return exit code 3 if any unresolved ids remain."""
    t0 = time.time()
    today_dir = get_today_dir()
    batches_dir = today_dir / "batches"
    if not batches_dir.exists():
        print("Lỗi: Không tìm thấy thư mục batches.")
        return 1

    topics_data = config.load("topics").get("topics", {})
    topics_set = set(topics_data.keys())
    valid_rows, problem_ids = batches.merge_results(batches_dir, topics=topics_set)

    # Save valid rows to persistent cache and prune older than 7 days
    cache.update_and_prune_cache(valid_rows)

    duration = time.time() - t0
    cache.log_step("collect", duration, valid=len(valid_rows), problems=len(problem_ids))

    if problem_ids:
        print(f"Cần chạy lại ({len(problem_ids)} bài): {', '.join(problem_ids)}")
        return 3

    print(f"Hoàn thành thu thập {len(valid_rows)} bài viết.")
    return 0


def run_cluster(skip_merge: bool = False, verbose: bool = False) -> int:
    """Cluster classified articles (new + cached), score them, and prepare merge plan or clusters.json."""
    t0 = time.time()
    today_dir = get_today_dir()
    articles_path = today_dir / "articles.json"
    if not articles_path.exists():
        print("Lỗi: Không tìm thấy articles.json.")
        return 1

    with open(articles_path, "r", encoding="utf-8") as f:
        art_items = json.load(f)
    articles = [Article(**item) for item in art_items]
    articles_by_id = {a.id: a for a in articles}

    # Load persistent cache classifications and merge with today's batches
    cached_data = cache.load_cache()
    classified_by_id = dict(cached_data)

    batches_dir = today_dir / "batches"
    if batches_dir.exists():
        valid_rows, _ = batches.merge_results(batches_dir)
        for r in valid_rows:
            classified_by_id[r["id"]] = r

    # Filter to articles that have classification data
    classified_items = []
    for a in articles:
        if a.id in classified_by_id:
            row = dict(classified_by_id[a.id])
            row["id"] = a.id
            classified_items.append(row)

    clusters = cluster.cluster(articles, classified_items)
    profile = config.load("profile")
    now = datetime.now(timezone.utc)

    for cl in clusters:
        cluster.score(cl, articles_by_id, classified_by_id, profile, now)

    duration = time.time() - t0
    cache.log_step("cluster", duration, clusters=len(clusters))

    if skip_merge:
        selected = cluster.select(clusters, profile)
        clusters_path = today_dir / "clusters.json"
        with open(clusters_path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in selected], f, ensure_ascii=False, indent=2)

        if verbose:
            for c in selected:
                print(f"[{c.cluster_id}] (Score: {c.score:.2f}, {c.source_count} nguồn) {c.headline}")
        else:
            print(f"Hoàn thành gom cụm ({len(selected)} cụm tin).")

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

    if verbose:
        print(f"Đã tạo clusters-raw.json ({len(clusters)} cụm) và merge-input.json.")
        print("Bước tiếp theo: Dispatch subagent cluster-merger để tạo merge-result.json, sau đó gọi 'merge'.")
    else:
        print(f"Đã tạo {len(clusters)} cụm tin sơ bộ.")
    return 0


def run_finish(verbose: bool = False) -> int:
    """Collect results and cluster in one call. If any batch is incomplete, print RERUN lines and exit 3."""
    today_dir = get_today_dir()
    batches_dir = today_dir / "batches"

    topics_data = config.load("topics").get("topics", {})
    topics_set = set(topics_data.keys())

    batch_files = sorted(batches_dir.glob("batch-*.json")) if batches_dir.exists() else []
    rerun_batches = []
    all_valid_rows = []

    for b_path in batch_files:
        try:
            with open(b_path, "r", encoding="utf-8") as f:
                b_data = json.load(f)
            expected_ids = [item["id"] for item in b_data if isinstance(item, dict) and "id" in item]
        except Exception:
            rerun_batches.append(b_path)
            continue

        r_path = batches_dir / b_path.name.replace("batch-", "result-").replace(".json", ".txt")
        if not r_path.exists():
            rerun_batches.append(b_path)
            continue

        try:
            raw = r_path.read_text(encoding="utf-8")
            valid, problems = batches.validate_lines(raw, expected_ids, topics_set)
            if problems:
                rerun_batches.append(b_path)
            else:
                all_valid_rows.extend(valid)
        except Exception:
            rerun_batches.append(b_path)

    if rerun_batches:
        for b_path in rerun_batches:
            print(f"RERUN {b_path}")
        return 3

    # All batches are complete
    if all_valid_rows:
        cache.update_and_prune_cache(all_valid_rows)

    return run_cluster(skip_merge=True, verbose=verbose)


def run_brief(verbose: bool = False) -> int:
    """Print compact brief pack with top clusters and verified source URLs."""
    t0 = time.time()
    today_dir = get_today_dir()
    clusters_path = today_dir / "clusters.json"
    if not clusters_path.exists():
        clusters_path = today_dir / "clusters-raw.json"
    if not clusters_path.exists():
        print("Lỗi: Không tìm thấy clusters.json.")
        return 1

    articles_path = today_dir / "articles.json"
    if not articles_path.exists():
        print("Lỗi: Không tìm thấy articles.json.")
        return 1

    with open(clusters_path, "r", encoding="utf-8") as f:
        clusters_data = json.load(f)
    with open(articles_path, "r", encoding="utf-8") as f:
        articles_data = json.load(f)

    articles_by_id = {a["id"]: a for a in articles_data}

    # Classifications for article importance
    cached_data = cache.load_cache()
    classified_by_id = dict(cached_data)
    batches_dir = today_dir / "batches"
    if batches_dir.exists():
        valid_rows, _ = batches.merge_results(batches_dir)
        for r in valid_rows:
            classified_by_id[r["id"]] = r

    profile = config.load("profile")
    brief_limit = profile.get("brief_clusters", 40)
    links_limit = profile.get("brief_links_per_cluster", 2)
    topics_cfg = config.load("topics").get("topics", {})
    sources_cfg = config.load("sources").get("sources", {})

    sorted_clusters = sorted(
        clusters_data,
        key=lambda c: c.get("score", 0.0),
        reverse=True
    )[:brief_limit]

    duration = time.time() - t0
    cache.log_step("brief", duration, clusters=len(sorted_clusters))

    today_date_str = datetime.now().strftime("%d/%m/%Y")
    print(f"Ngày: {today_date_str}")

    for cl in sorted_clusters:
        cid = cl.get("cluster_id", "")
        cscore = float(cl.get("score", 0.0))
        c_src_count = cl.get("source_count", 1)
        cheadline = cl.get("headline", "")
        ctopics = cl.get("topics", [])

        topic_labels = []
        for t in ctopics:
            lbl = topics_cfg.get(t, {}).get("label", t)
            if lbl not in topic_labels:
                topic_labels.append(lbl)
        topics_str = ", ".join(topic_labels)

        header_line = f"#{cid} | điểm {cscore:.1f} | {c_src_count} nguồn | {topics_str} | {cheadline}"

        # Collect articles in this cluster
        art_ids = cl.get("article_ids", [])
        cluster_arts = [articles_by_id[aid] for aid in art_ids if aid in articles_by_id]

        # Sort by importance descending
        def get_importance(art_dict):
            return classified_by_id.get(art_dict["id"], {}).get("importance", 0)

        cluster_arts.sort(key=get_importance, reverse=True)

        # Best lede (highest importance first, cut to <= 160 chars)
        best_lede_raw = ""
        for art in cluster_arts:
            raw_s = art.get("summary_raw", "")
            if raw_s:
                best_lede_raw = raw_s
                break
        best_lede = batches.truncate_at_word(best_lede_raw, 160, ellipsis="…")

        # Distinct sources links
        links = []
        seen_sources = set()
        for art in cluster_arts:
            src = art.get("source", "")
            if src not in seen_sources:
                seen_sources.add(src)
                s_label = sources_cfg.get(src, {}).get("label") or src.title()
                url = art.get("url", "")
                links.append(f"[{s_label}]({url})")
                if len(links) >= links_limit:
                    break

        links_str = " ".join(links)
        if best_lede and links_str:
            indented_line = f"  {best_lede} {links_str}"
        elif best_lede:
            indented_line = f"  {best_lede}"
        elif links_str:
            indented_line = f"  {links_str}"
        else:
            indented_line = "  "

        print(header_line)
        print(indented_line)

    # Source health problem block (feed problems only)
    today_health_path = today_dir / "health.json"
    healths = []
    if today_health_path.exists():
        try:
            with open(today_health_path, "r", encoding="utf-8") as f:
                healths = [health.SourceHealth(**item) for item in json.load(f)]
        except Exception:
            pass

    problem_lines = health.get_brief_problem_lines(healths, sources_cfg=sources_cfg)
    if problem_lines:
        print("\nNGUỒN LỖI")
        for line in problem_lines:
            print(line)

    return 0


def run_merge(verbose: bool = False) -> int:
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

    cached_data = cache.load_cache()
    classified_by_id = dict(cached_data)
    batches_dir = today_dir / "batches"
    if batches_dir.exists():
        valid_rows, _ = batches.merge_results(batches_dir)
        for r in valid_rows:
            classified_by_id[r["id"]] = r

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
    sources_cfg = config.load("sources")
    max_per_cluster = profile.get("fulltext_articles_per_cluster", 2)
    max_chars = profile.get("fulltext_max_chars", 3500)

    cached_data = cache.load_cache()
    classified_by_id = dict(cached_data)
    batches_dir = today_dir / "batches"
    if batches_dir.exists():
        try:
            valid_rows, _ = batches.merge_results(batches_dir)
            for r in valid_rows:
                classified_by_id[r["id"]] = r
        except Exception:
            pass

    status_file = fulltext_dir / "_status.json"
    status_data = {}
    if status_file.exists():
        try:
            status_data = json.loads(status_file.read_text(encoding="utf-8"))
        except Exception:
            status_data = {}

    run_results: List[str] = []
    run_article_statuses: List[dict] = []
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
        for art, _ in cluster_articles:
            src = art.get("source", "")
            if src not in seen_sources:
                selected_arts.append(art)
                seen_sources.add(src)
                if len(selected_arts) >= max_per_cluster:
                    break

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
            tier = ""
            chars = 0
            error_msg = ""
            body_text = summary_raw

            hints = fulltext_check.get_effective_hints(src, sources_cfg, profile)

            try:
                raw_bytes = fetch.fetch_url(art["url"], timeout=10, retries=1)
                extracted, tier = extract.extract_with_tier(
                    raw_bytes.decode("utf-8", errors="ignore"),
                    title=title,
                    max_chars=max_chars,
                    hints=hints
                )
                if extracted:
                    status = "full" if tier in ("json-ld", "article", "hint") else "degraded"
                    body_text = extracted
                    chars = len(body_text)
                else:
                    status = "summary_only"
                    body_text = summary_raw
                    chars = len(body_text)
            except Exception as e:
                status = "error"
                tier = ""
                error_msg = str(e)
                body_text = summary_raw
                chars = len(body_text)

            txt_path.write_text(body_text, encoding="utf-8")

            status_entry = {
                "source": src,
                "status": status,
                "tier": tier,
                "chars": chars,
                "error": error_msg,
            }
            status_data[aid] = status_entry
            run_results.append(status)
            run_article_statuses.append(status_entry)

            label = "[toàn văn]" if status in ("full", "degraded") else "[chỉ có tóm tắt RSS]"
            if status == "error":
                print(f"- [{src}] {title} [lỗi tải trang: {error_msg}] {label}\n  {body_text[:300]}...\n")
            else:
                print(f"- [{src}] {title} {label}\n  {body_text[:300]}...\n")

    status_file.write_text(json.dumps(status_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # Update fulltext-health.json aggregated per source
    source_aggregates: Dict[str, List[Tuple[str, str]]] = {}
    for entry in run_article_statuses:
        src = entry.get("source")
        if not src:
            continue
        st = entry.get("status", "summary_only")
        tr = entry.get("tier", "")
        source_aggregates.setdefault(src, []).append((st, tr))

    fulltext_records = []
    for src, items in source_aggregates.items():
        statuses = [s for s, _ in items]
        if "full" in statuses:
            final_status = "full"
            final_tier = next((t for s, t in items if s == "full"), "")
        elif "degraded" in statuses:
            final_status = "degraded"
            final_tier = next((t for s, t in items if s == "degraded"), "")
        elif "summary_only" in statuses:
            final_status = "summary_only"
            final_tier = ""
        else:
            final_status = "error"
            final_tier = ""
        fulltext_records.append({
            "source": src,
            "status": final_status,
            "tier": final_tier,
        })
    if fulltext_records:
        health.record_fulltext_health(fulltext_records)

    total_run = len(run_results)
    full_count = sum(1 for s in run_results if s in ("full", "degraded"))
    summary_count = sum(1 for s in run_results if s == "summary_only")
    error_count = sum(1 for s in run_results if s == "error")
    print(f"Toàn văn: {full_count}/{total_run} bài; chỉ tóm tắt: {summary_count}; lỗi: {error_count}.")

    return 0


def run_run(
    *,
    groups: Optional[List[str]] = None,
    only: Optional[List[str]] = None,
    limit: Optional[int] = None,
    since_str: Optional[str] = None,
    query: Optional[str] = None,
    opener=None,
    verbose: bool = False
) -> int:
    """Execute run = fetch + prepare (+ cache prune)."""
    # Cache prune
    cache.prune_cache()

    f_ret = run_fetch(
        groups=groups,
        only=only,
        limit=limit,
        since_str=since_str,
        query=query,
        opener=opener,
        verbose=verbose
    )
    if f_ret != 0:
        return f_ret

    p_ret = run_prepare(verbose=verbose)
    if p_ret != 0:
        return p_ret

    if verbose:
        print("\nHoàn thành fetch + prepare.")
        print("Bước tiếp theo: Dispatch các subagent news-classifier song song theo từng batch,")
        print("sau đó gọi 'finish'.")

    return 0


def run_stats() -> int:
    """Print the last run's step timings from the log file."""
    stats = cache.get_last_run_stats()
    if not stats:
        print("Chưa có thông tin thời gian thực thi.")
        return 0

    print("Thời gian thực thi các bước gần nhất:")
    for step_name, dur in stats:
        print(f"- {step_name}: {dur:.1f}s")
    return 0

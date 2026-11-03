"""Fin-News command line interface."""
import argparse
import json
import os
from pathlib import Path
import sys
from typing import List, Optional

# Ensure fin_news can be imported when cli.py is executed directly
CLI_DIR = Path(__file__).resolve().parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

from fin_news import config
from fin_news import discover
from fin_news import doctor
from fin_news import fetch
from fin_news import fulltext_check
from fin_news import health
from fin_news import pipeline


def _parse_list_arg(val: Optional[str]) -> Optional[List[str]]:
    if not val:
        return None
    return [item.strip() for item in val.split(",") if item.strip()]


def main(argv=None) -> int:
    # Ensure stdout/stderr output in UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Fin-News CLI workflow tool")
    parser.add_argument("--verbose", "-v", action="store_true", help="Detailed output")
    subparsers = parser.add_subparsers(dest="subcommand", help="Available subcommands")

    # fetch
    fetch_parser = subparsers.add_parser("fetch", help="Fetch articles from RSS/news sources")
    fetch_parser.add_argument("--groups", help="Comma-separated source groups")
    fetch_parser.add_argument("--only", help="Comma-separated source IDs")
    fetch_parser.add_argument("--limit", type=int, help="Per-source article limit")
    fetch_parser.add_argument("--since", help="Fetch articles newer than e.g. 7d")
    fetch_parser.add_argument("--query", help="Keyword query (bypasses quota)")
    fetch_parser.add_argument("--topics", help="Comma-separated topic slugs")
    fetch_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # prepare
    prepare_parser = subparsers.add_parser("prepare", help="Dedupe, filter, and prepare System 1 batches")
    prepare_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # collect
    collect_parser = subparsers.add_parser("collect", help="Merge System 1 classification results")
    collect_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # cluster
    cluster_parser = subparsers.add_parser("cluster", help="Cluster articles and prepare merge plan")
    cluster_parser.add_argument("--skip-merge", action="store_true", help="Skip merge step and write clusters.json directly")
    cluster_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # finish
    finish_parser = subparsers.add_parser("finish", help="Collect and cluster in one call")
    finish_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # brief
    brief_parser = subparsers.add_parser("brief", help="Print compact brief pack with source links")
    brief_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # stats
    subparsers.add_parser("stats", help="Print step execution timings of the last run")

    # merge
    merge_parser = subparsers.add_parser("merge", help="Apply cluster merge results and write clusters.json")
    merge_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    # fulltext
    fulltext_parser = subparsers.add_parser("fulltext", help="Fetch article fulltext for clusters")
    fulltext_parser.add_argument("cluster_id", nargs="+", help="Cluster ID(s) to fetch")

    # health
    subparsers.add_parser("health", help="Report source health status")

    # config
    config_parser = subparsers.add_parser("config", help="Manage configuration")
    config_parser.add_argument("action", choices=["get", "set", "unset"], help="Config action")
    config_parser.add_argument("file", help="Config file name (sources, topics, profile)")
    config_parser.add_argument("key", help="Dotted configuration key")
    config_parser.add_argument("value", nargs="?", default=None, help="Value to set")

    # add-source
    add_src_parser = subparsers.add_parser("add-source", help="Discover and add new RSS source")
    add_src_parser.add_argument("url", help="URL of website or feed")
    add_src_parser.add_argument("--id", dest="source_id", help="Source ID identifier")
    add_src_parser.add_argument("--group", default="general", help="Source group")
    add_src_parser.add_argument("--label", help="Friendly source label")

    # test-source
    test_src_parser = subparsers.add_parser("test-source", help="Test a specific source")
    test_src_parser.add_argument("source_id", help="Source ID to test")
    test_src_parser.add_argument("--fulltext", action="store_true", help="Test full-text extraction for source")

    # doctor
    doctor_parser = subparsers.add_parser("doctor", help="Run diagnostic health checks")
    doctor_parser.add_argument("--fulltext", action="store_true", help="Diagnose live full-text extraction across all sources")

    # run
    run_parser = subparsers.add_parser("run", help="Run fetch and prepare, stopping before classification")
    run_parser.add_argument("--groups", help="Comma-separated source groups")
    run_parser.add_argument("--only", help="Comma-separated source IDs")
    run_parser.add_argument("--limit", type=int, help="Per-source article limit")
    run_parser.add_argument("--since", help="Fetch articles newer than e.g. 7d")
    run_parser.add_argument("--query", help="Keyword query")
    run_parser.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="Detailed output")

    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 0

    cmd = args.subcommand
    verbose = getattr(args, "verbose", False)

    if cmd == "fetch":
        return pipeline.run_fetch(
            groups=_parse_list_arg(args.groups),
            only=_parse_list_arg(args.only),
            limit=args.limit,
            since_str=args.since,
            query=args.query,
            topics=_parse_list_arg(args.topics),
            verbose=verbose,
        )

    elif cmd == "prepare":
        return pipeline.run_prepare(verbose=verbose)

    elif cmd == "collect":
        return pipeline.run_collect(verbose=verbose)

    elif cmd == "cluster":
        return pipeline.run_cluster(skip_merge=args.skip_merge, verbose=verbose)

    elif cmd == "finish":
        return pipeline.run_finish(verbose=verbose)

    elif cmd == "brief":
        return pipeline.run_brief(verbose=verbose)

    elif cmd == "stats":
        return pipeline.run_stats()

    elif cmd == "merge":
        return pipeline.run_merge(verbose=verbose)

    elif cmd == "fulltext":
        return pipeline.run_fulltext(args.cluster_id)

    elif cmd == "health":
        today_health = pipeline.get_today_dir() / "health.json"
        healths = []
        if today_health.exists():
            try:
                with open(today_health, "r", encoding="utf-8") as f:
                    healths = [health.SourceHealth(**item) for item in json.load(f)]
            except Exception:
                pass
        print(health.render(healths))
        return 0

    elif cmd == "config":
        if args.action == "get":
            data = config.load(args.file)
            val = config._get_nested(data, args.key.split("."))
            print(json.dumps(val, ensure_ascii=False, indent=2) if isinstance(val, (dict, list)) else val)
            return 0
        elif args.action == "set":
            if args.value is None:
                print("Lỗi: Thiếu giá trị cần thiết lập.")
                return 1
            # Parse json value if possible, else string
            val_to_set = args.value
            try:
                val_to_set = json.loads(args.value)
            except Exception:
                pass
            old_val, new_val = config.set_value(args.file, args.key, val_to_set)
            print(f"{old_val} → {new_val}")
            return 0
        elif args.action == "unset":
            config.unset(args.file, args.key)
            print(f"Đã xoá {args.key} khỏi {args.file}.json (khôi phục mặc định).")
            return 0

    elif cmd == "add-source":
        res = discover.add_source(args.url, source_id=args.source_id, group=args.group, label=args.label)
        if not res.get("found", True):
            print(f"Không tìm thấy feed RSS ({res.get('hint')}).")
            return 1
        print(f"Đã thêm nguồn: {res.get('source_id')}")
        print(f"Feeds: {', '.join(res.get('feed_urls', []))}")
        print(f"Tiêu đề mẫu:\n" + "\n".join(f"- {t}" for t in res.get("sample_titles", [])))
        return 0

    elif cmd == "test-source":
        sources = config.load("sources").get("sources", {})
        if args.source_id not in sources:
            print(f"Nguồn '{args.source_id}' không tồn tại trong cấu hình.")
            return 1
        if getattr(args, "fulltext", False):
            profile = config.load("profile")
            res = fulltext_check.check_source(args.source_id, sources[args.source_id], profile)
            health.record_fulltext_health([res])
            status = res.get("status", "")
            tier = res.get("tier", "")
            chars = res.get("chars", 0)
            url = res.get("url", "")
            text = res.get("text", "")
            err = res.get("error", "")

            print(f"[{status.upper()}] {args.source_id}")
            print(f"- Tầng: {tier}")
            print(f"- Số ký tự: {chars}")
            print(f"- URL: {url}")
            if err:
                print(f"- Lỗi: {err}")
            if text:
                sample_text = text[:200].replace("\n", " ")
                print(f"- Trích đoạn: {sample_text}...")

            return 0 if status in ("full", "degraded") else 1
        else:
            h = discover.test_source(args.source_id, sources[args.source_id])
            print(f"[{h.status.upper()}] {h.source_id}: {h.detail}")
            return 0 if h.status == "ok" else 1

    elif cmd == "doctor":
        if getattr(args, "fulltext", False):
            results = doctor.run_fulltext()
            print("=== BÁO CÁO TOÀN VĂN (DOCTOR --FULLTEXT) ===")
            print(f"{'NGUỒN':<20} | {'TRẠNG THÁI':<12} | {'TẦNG':<10} | {'KÝ TỰ':<6} | URL")
            print("-" * 80)
            has_error = False
            for r in results:
                st = r.get("status", "")
                sid = r.get("source", "")
                tier = r.get("tier", "")
                chars = r.get("chars", 0)
                url = r.get("url", "")
                print(f"{sid:<20} | {st:<12} | {tier:<10} | {chars:<6} | {url}")
                if st in ("error", "summary_only"):
                    has_error = True
            if has_error:
                install_p, trouble_p = doctor.get_doc_paths()
                print(f"\nXem hướng dẫn: {install_p} và {trouble_p}")
            return 0 if not has_error else 1
        else:
            results = doctor.run()
            print("=== BÁO CÁO DOCTOR ===")
            all_passed = True
            for name, ok, detail in results:
                status_str = "OK" if ok else "FAIL"
                print(f"[{status_str:4}] {name:30} : {detail}")
                if not ok:
                    all_passed = False
            if not all_passed:
                install_p, trouble_p = doctor.get_doc_paths()
                print(f"\nXem hướng dẫn: {install_p} và {trouble_p}")
            return 0 if all_passed else 1

    elif cmd == "run":
        return pipeline.run_run(
            groups=_parse_list_arg(args.groups),
            only=_parse_list_arg(args.only),
            limit=args.limit,
            since_str=args.since,
            query=args.query,
            verbose=verbose,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

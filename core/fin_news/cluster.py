"""Clustering and scoring module."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import difflib
import json
from typing import Any, Dict, List, Optional, Set, Tuple

from .dedupe import strip_accents
from .models import Article


@dataclass
class Cluster:
    cluster_id: str
    headline: str
    topics: List[str]
    article_ids: List[str]
    source_count: int = 1
    score: float = 0.0
    needs_fulltext: bool = False


def cluster(
    articles: List[Article],
    classified: List[dict],
    threshold: float = 0.8
) -> List[Cluster]:
    """Group articles by event_key, then merge similar headlines, ignoring noise."""
    articles_by_id = {a.id: a for a in articles}
    non_noise = [c for c in classified if not c.get("is_noise", False)]

    groups: Dict[str, List[dict]] = {}
    group_order: List[str] = []

    for item in non_noise:
        ek = item.get("event_key", "default_event")
        if ek not in groups:
            groups[ek] = []
            group_order.append(ek)
        groups[ek].append(item)

    raw_clusters = []
    for ek in group_order:
        items = groups[ek]
        art_ids = [it["id"] for it in items]
        sources = set(articles_by_id[aid].source for aid in art_ids if aid in articles_by_id)

        all_topics = set()
        for it in items:
            for t in it.get("topics", []):
                all_topics.add(t)

        first_aid = art_ids[0] if art_ids else None
        headline = (
            articles_by_id[first_aid].title
            if first_aid and first_aid in articles_by_id
            else ek
        )

        raw_clusters.append({
            "headline": headline,
            "topics": list(all_topics),
            "article_ids": art_ids,
            "sources": sources,
        })

    # Merge clusters with similar headlines
    merged: List[dict] = []
    for rc in raw_clusters:
        norm_h = " ".join(strip_accents(rc["headline"].lower()).split())
        matched_idx = -1
        for idx, mc in enumerate(merged):
            m_norm = " ".join(strip_accents(mc["headline"].lower()).split())
            if difflib.SequenceMatcher(None, norm_h, m_norm).ratio() >= threshold:
                matched_idx = idx
                break
        if matched_idx >= 0:
            merged[matched_idx]["article_ids"].extend(rc["article_ids"])
            merged[matched_idx]["sources"].update(rc["sources"])
            merged[matched_idx]["topics"] = list(set(merged[matched_idx]["topics"] + rc["topics"]))
        else:
            merged.append(rc)

    clusters_out = []
    for idx, mc in enumerate(merged):
        clusters_out.append(Cluster(
            cluster_id=f"c-{idx+1:03d}",
            headline=mc["headline"],
            topics=mc["topics"],
            article_ids=mc["article_ids"],
            source_count=len(mc["sources"]),
        ))

    return clusters_out


def score(
    c: Cluster,
    articles_by_id: Dict[str, Article],
    classified_by_id: Dict[str, dict],
    profile: dict,
    now: datetime
) -> float:
    """Calculate cluster score = importance + source bonus + recency bonus + watchlist bonus."""
    weights = profile.get("weights", {})

    # 1. Max importance
    importances = [
        classified_by_id[aid].get("importance", 0)
        for aid in c.article_ids
        if aid in classified_by_id
    ]
    max_imp = max(importances, default=0.0)
    w_imp = weights.get("max_importance", 1.0) * float(max_imp)

    # 2. Source bonus
    # 1 source -> 0, 2-3 -> 1.0, >=4 -> 2.0
    src_weights = weights.get("source_bonus", [0, 1.0, 2.0])
    if c.source_count <= 1:
        s_bonus = float(src_weights[0])
    elif 2 <= c.source_count <= 3:
        s_bonus = float(src_weights[1])
    else:
        s_bonus = float(src_weights[2])

    # 3. Recency bonus
    # 1.0 if <= 3 h old, linear to 0 at 24 h; unknown date -> 0
    w_recency = weights.get("recency_bonus", 1.0)
    newest_dt = None
    for aid in c.article_ids:
        art = articles_by_id.get(aid)
        if art and art.published_at:
            try:
                dt = datetime.fromisoformat(art.published_at)
                if newest_dt is None or dt > newest_dt:
                    newest_dt = dt
            except Exception:
                pass

    if newest_dt is None:
        r_bonus = 0.0
    else:
        # Align timezones
        if now.tzinfo is None and newest_dt.tzinfo is not None:
            now = now.replace(tzinfo=newest_dt.tzinfo)
        elif now.tzinfo is not None and newest_dt.tzinfo is None:
            newest_dt = newest_dt.replace(tzinfo=now.tzinfo)

        age_seconds = (now - newest_dt).total_seconds()
        age_hours = max(0.0, age_seconds / 3600.0)
        if age_hours <= 3.0:
            r_bonus = w_recency * 1.0
        elif age_hours < 24.0:
            r_bonus = w_recency * max(0.0, (1.0 - (age_hours - 3.0) / 21.0))
        else:
            r_bonus = 0.0

    # 4. Watchlist bonus
    # 1.5 if any title or lede matches profile.watchlist
    watchlist = profile.get("watchlist", [])
    w_bonus = 0.0
    if watchlist:
        norm_watch = [strip_accents(w.lower()) for w in watchlist if w]
        matched = False
        for aid in c.article_ids:
            art = articles_by_id.get(aid)
            if art:
                title = art.title or ""
                lede = art.summary_raw or ""
                check_text = strip_accents(f"{title} {lede}".lower())
                if any(w in check_text for w in norm_watch):
                    matched = True
                    break
        if matched:
            w_bonus = float(weights.get("watchlist_bonus", 1.5))

    total = w_imp + s_bonus + r_bonus + w_bonus
    c.score = float(total)
    return c.score


def select(clusters: List[Cluster], profile: dict) -> List[Cluster]:
    """Select top max_clusters by score, setting needs_fulltext=True for top digest_items * 2."""
    max_clusters = profile.get("max_clusters", 40)
    digest_items = profile.get("digest_items", 5)
    fulltext_limit = digest_items * 2

    sorted_clusters = sorted(clusters, key=lambda c: c.score, reverse=True)
    selected = sorted_clusters[:max_clusters]

    for idx, cl in enumerate(selected):
        cl.needs_fulltext = (idx < fulltext_limit)

    return selected


def merge_plan(clusters: List[Cluster], articles_by_id: Dict[str, Any]) -> List[dict]:
    """Prepare merge plan input for Haiku agent, listing all clusters sorted by cluster_id."""
    plan = []
    for c in clusters:
        sources_set = set()
        for aid in c.article_ids:
            art = articles_by_id.get(aid)
            if art:
                src = art.source if hasattr(art, "source") else art.get("source")
                if src:
                    sources_set.add(src)
        plan.append({
            "cluster_id": c.cluster_id,
            "headline": c.headline,
            "topics": list(c.topics),
            "sources": sorted(list(sources_set)),
        })
    plan.sort(key=lambda x: x["cluster_id"])
    return plan


def validate_merge(raw: str, cluster_ids: List[str]) -> Tuple[List[List[str]], List[str]]:
    """Validate merge JSON output against allowed cluster IDs."""
    if not raw or not isinstance(raw, str):
        return [], ["unparseable"]

    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or "groups" not in data or not isinstance(data["groups"], list):
            return [], ["unparseable"]
    except Exception:
        return [], ["unparseable"]

    valid_ids = set(cluster_ids)
    valid_groups: List[List[str]] = []
    problems: List[str] = []
    seen_in_groups: Set[str] = set()

    for group in data["groups"]:
        if not isinstance(group, list):
            problems.append(f"Nhóm không hợp lệ: phải là danh sách ({group})")
            continue
        if len(group) < 2:
            problems.append(f"Nhóm {group} bị loại: cần ít nhất 2 cluster ID")
            continue
        if not all(isinstance(cid, str) for cid in group):
            problems.append(f"Nhóm {group} bị loại: cluster ID phải là chuỗi ký tự")
            continue
        if len(set(group)) != len(group):
            problems.append(f"Nhóm {group} bị loại: chứa cluster ID trùng lặp nội bộ")
            continue
        unknown = [cid for cid in group if cid not in valid_ids]
        if unknown:
            problems.append(f"Nhóm {group} bị loại: cluster ID không tồn tại ({', '.join(unknown)})")
            continue
        overlap = [cid for cid in group if cid in seen_in_groups]
        if overlap:
            problems.append(f"Nhóm {group} bị loại: cluster ID đã xuất hiện trong nhóm khác ({', '.join(overlap)})")
            continue

        seen_in_groups.update(group)
        valid_groups.append(group)

    return valid_groups, problems


def apply_merge(
    clusters: List[Cluster],
    groups: List[List[str]],
    articles_by_id: Dict[str, Any],
    classified_by_id: Dict[str, dict],
    profile: dict,
    now: datetime
) -> List[Cluster]:
    """Merge groups of clusters, recompute score and source_count, and select top clusters."""
    cluster_by_id = {c.cluster_id: c for c in clusters}
    handled_cids: Set[str] = set()
    merged_clusters: List[Cluster] = []

    for group in groups:
        members = [cluster_by_id[cid] for cid in group if cid in cluster_by_id]
        if not members:
            continue
        handled_cids.update(group)

        # Union of article_ids
        seen_art = set()
        art_ids = []
        for m in members:
            for aid in m.article_ids:
                if aid not in seen_art:
                    seen_art.add(aid)
                    art_ids.append(aid)

        # Union of topics
        seen_top = set()
        topics_union = []
        for m in members:
            for t in m.topics:
                if t not in seen_top:
                    seen_top.add(t)
                    topics_union.append(t)

        # Headline of member with highest current score
        best_member = max(members, key=lambda m: m.score)
        headline = best_member.headline

        # Distinct sources over union
        sources = set()
        for aid in art_ids:
            art = articles_by_id.get(aid)
            if art:
                src = art.source if hasattr(art, "source") else art.get("source")
                if src:
                    sources.add(src)
        source_count = len(sources)

        # Lowest ID in group
        min_id = min(m.cluster_id for m in members)

        new_cluster = Cluster(
            cluster_id=min_id,
            headline=headline,
            topics=topics_union,
            article_ids=art_ids,
            source_count=source_count,
        )
        score(new_cluster, articles_by_id, classified_by_id, profile, now)
        merged_clusters.append(new_cluster)

    # Untouched clusters
    for c in clusters:
        if c.cluster_id not in handled_cids:
            merged_clusters.append(c)

    return select(merged_clusters, profile)

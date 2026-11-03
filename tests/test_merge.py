from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import cluster
from fin_news.cluster import Cluster
from fin_news.models import Article


def load_fixtures():
    fix_path = Path(__file__).resolve().parent / "fixtures" / "merge_headlines.json"
    with open(fix_path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.headlines = load_fixtures()
        self.profile = {
            "max_clusters": 40,
            "digest_items": 5,
            "weights": {
                "max_importance": 1.0,
                "source_bonus": [0.0, 1.0, 2.0],
                "recency_bonus": 1.0,
                "watchlist_bonus": 1.5,
            },
        }
        self.now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)

    def test_merge_plan_lists_every_cluster_with_headline_and_sources(self):
        articles_by_id = {
            "a1": Article(
                id="a1", source="cafef", source_group="vimo", url="http://1",
                title=self.headlines["fdi_10_months"][0], summary_raw="",
                published_at="2026-11-03T10:00:00+07:00", fetched_at="2026-11-03T10:05:00+07:00"
            ),
            "a2": Article(
                id="a2", source="vietstock", source_group="vimo", url="http://2",
                title=self.headlines["fdi_10_months"][1], summary_raw="",
                published_at="2026-11-03T10:00:00+07:00", fetched_at="2026-11-03T10:05:00+07:00"
            ),
            "a3": Article(
                id="a3", source="cafef", source_group="vimo", url="http://3",
                title=self.headlines["cpi"][0], summary_raw="",
                published_at="2026-11-03T10:00:00+07:00", fetched_at="2026-11-03T10:05:00+07:00"
            ),
        }
        clusters = [
            Cluster(
                cluster_id="c-002",
                headline=self.headlines["cpi"][0],
                topics=["vi-mo-chinh-sach"],
                article_ids=["a3"],
                source_count=1,
            ),
            Cluster(
                cluster_id="c-001",
                headline=self.headlines["fdi_10_months"][0],
                topics=["vi-mo-chinh-sach"],
                article_ids=["a1", "a2"],
                source_count=2,
            ),
        ]

        plan = cluster.merge_plan(clusters, articles_by_id)
        # Must be sorted by cluster_id
        self.assertEqual(len(plan), 2)
        self.assertEqual(plan[0]["cluster_id"], "c-001")
        self.assertEqual(plan[0]["headline"], self.headlines["fdi_10_months"][0])
        self.assertEqual(plan[0]["topics"], ["vi-mo-chinh-sach"])
        self.assertEqual(sorted(plan[0]["sources"]), ["cafef", "vietstock"])

        self.assertEqual(plan[1]["cluster_id"], "c-002")
        self.assertEqual(plan[1]["headline"], self.headlines["cpi"][0])
        self.assertEqual(plan[1]["sources"], ["cafef"])

    def test_validate_merge_accepts_good_groups(self):
        raw = json.dumps({"groups": [["c-001", "c-002"], ["c-003", "c-004"]]})
        cluster_ids = ["c-001", "c-002", "c-003", "c-004", "c-005"]
        valid_groups, problems = cluster.validate_merge(raw, cluster_ids)
        self.assertEqual(valid_groups, [["c-001", "c-002"], ["c-003", "c-004"]])
        self.assertEqual(problems, [])

    def test_validate_merge_drops_group_with_unknown_id(self):
        raw = json.dumps({"groups": [["c-001", "c-999"], ["c-002", "c-003"]]})
        cluster_ids = ["c-001", "c-002", "c-003"]
        valid_groups, problems = cluster.validate_merge(raw, cluster_ids)
        self.assertEqual(valid_groups, [["c-002", "c-003"]])
        self.assertEqual(len(problems), 1)
        self.assertIn("c-999", problems[0])

    def test_validate_merge_drops_group_with_overlapping_id(self):
        raw = json.dumps({"groups": [["c-001", "c-002"], ["c-002", "c-003"]]})
        cluster_ids = ["c-001", "c-002", "c-003"]
        valid_groups, problems = cluster.validate_merge(raw, cluster_ids)
        self.assertEqual(valid_groups, [["c-001", "c-002"]])
        self.assertEqual(len(problems), 1)
        self.assertIn("c-002", problems[0])

    def test_validate_merge_drops_singleton_group(self):
        raw = json.dumps({"groups": [["c-001"], ["c-002", "c-003"]]})
        cluster_ids = ["c-001", "c-002", "c-003"]
        valid_groups, problems = cluster.validate_merge(raw, cluster_ids)
        self.assertEqual(valid_groups, [["c-002", "c-003"]])
        self.assertEqual(len(problems), 1)
        self.assertIn("c-001", problems[0])

    def test_validate_merge_unparseable_json(self):
        raw = "Invalid { json"
        cluster_ids = ["c-001", "c-002"]
        valid_groups, problems = cluster.validate_merge(raw, cluster_ids)
        self.assertEqual(valid_groups, [])
        self.assertEqual(problems, ["unparseable"])

    def test_apply_merge_recomputes_source_count_and_score(self):
        # Two FDI clusters from different sources
        a1 = Article(id="a1", source="cafef", source_group="g1", url="http://1",
                     title=self.headlines["fdi_10_months"][0], summary_raw="",
                     published_at="2026-11-03T10:00:00+07:00", fetched_at="2026-11-03T10:05:00+07:00")
        a2 = Article(id="a2", source="vietstock", source_group="g1", url="http://2",
                     title=self.headlines["fdi_10_months"][1], summary_raw="",
                     published_at="2026-11-03T10:00:00+07:00", fetched_at="2026-11-03T10:05:00+07:00")
        articles_by_id = {"a1": a1, "a2": a2}
        classified_by_id = {
            "a1": {"id": "a1", "importance": 3, "entities": [], "is_noise": False},
            "a2": {"id": "a2", "importance": 3, "entities": [], "is_noise": False},
        }

        c1 = Cluster(cluster_id="c-001", headline=a1.title, topics=["vi-mo-chinh-sach"],
                     article_ids=["a1"], source_count=1)
        c2 = Cluster(cluster_id="c-002", headline=a2.title, topics=["vi-mo-chinh-sach"],
                     article_ids=["a2"], source_count=1)

        cluster.score(c1, articles_by_id, classified_by_id, self.profile, self.now)
        cluster.score(c2, articles_by_id, classified_by_id, self.profile, self.now)

        score_c1_before = c1.score
        score_c2_before = c2.score

        merged = cluster.apply_merge(
            [c1, c2],
            [["c-001", "c-002"]],
            articles_by_id,
            classified_by_id,
            self.profile,
            self.now,
        )

        self.assertEqual(len(merged), 1)
        m = merged[0]
        self.assertEqual(m.source_count, 2)
        # Because source bonus for 2 sources is 1.0 (vs 0 for 1 source), score >= each member
        self.assertGreaterEqual(m.score, score_c1_before)
        self.assertGreaterEqual(m.score, score_c2_before)

    def test_apply_merge_leaves_unlisted_clusters_untouched(self):
        a1 = Article(id="a1", source="s1", source_group="g1", url="http://1",
                     title="T1", summary_raw="", published_at="2026-11-03T10:00:00+07:00", fetched_at="")
        a2 = Article(id="a2", source="s2", source_group="g1", url="http://2",
                     title="T2", summary_raw="", published_at="2026-11-03T10:00:00+07:00", fetched_at="")
        a3 = Article(id="a3", source="s3", source_group="g1", url="http://3",
                     title="T3", summary_raw="", published_at="2026-11-03T10:00:00+07:00", fetched_at="")
        articles_by_id = {"a1": a1, "a2": a2, "a3": a3}
        classified_by_id = {
            "a1": {"id": "a1", "importance": 2, "entities": [], "is_noise": False},
            "a2": {"id": "a2", "importance": 2, "entities": [], "is_noise": False},
            "a3": {"id": "a3", "importance": 4, "entities": [], "is_noise": False},
        }

        c1 = Cluster(cluster_id="c-001", headline="T1", topics=["ngan-hang"], article_ids=["a1"], source_count=1)
        c2 = Cluster(cluster_id="c-002", headline="T2", topics=["ngan-hang"], article_ids=["a2"], source_count=1)
        c3 = Cluster(cluster_id="c-003", headline="T3", topics=["chung-khoan"], article_ids=["a3"], source_count=1)

        for c in [c1, c2, c3]:
            cluster.score(c, articles_by_id, classified_by_id, self.profile, self.now)

        merged = cluster.apply_merge(
            [c1, c2, c3],
            [["c-001", "c-002"]],
            articles_by_id,
            classified_by_id,
            self.profile,
            self.now,
        )

        cluster_ids = [c.cluster_id for c in merged]
        self.assertIn("c-003", cluster_ids)
        c3_res = next(c for c in merged if c.cluster_id == "c-003")
        self.assertEqual(c3_res.headline, "T3")
        self.assertEqual(c3_res.article_ids, ["a3"])

    def test_apply_merge_uses_lowest_id_and_best_headline(self):
        a1 = Article(id="a1", source="s1", source_group="g1", url="http://1",
                     title="Lower score headline", summary_raw="",
                     published_at="2026-11-03T10:00:00+07:00", fetched_at="")
        a2 = Article(id="a2", source="s2", source_group="g1", url="http://2",
                     title="Best headline with high importance", summary_raw="",
                     published_at="2026-11-03T10:00:00+07:00", fetched_at="")
        articles_by_id = {"a1": a1, "a2": a2}
        classified_by_id = {
            "a1": {"id": "a1", "importance": 1, "entities": [], "is_noise": False},
            "a2": {"id": "a2", "importance": 5, "entities": [], "is_noise": False},
        }

        # c-002 has lower score, c-005 has higher score
        c2 = Cluster(cluster_id="c-002", headline=a1.title, topics=["vang-ty-gia"], article_ids=["a1"], source_count=1)
        c5 = Cluster(cluster_id="c-005", headline=a2.title, topics=["vang-ty-gia"], article_ids=["a2"], source_count=1)

        cluster.score(c2, articles_by_id, classified_by_id, self.profile, self.now)
        cluster.score(c5, articles_by_id, classified_by_id, self.profile, self.now)

        merged = cluster.apply_merge(
            [c5, c2],
            [["c-005", "c-002"]],
            articles_by_id,
            classified_by_id,
            self.profile,
            self.now,
        )

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].cluster_id, "c-002")
        self.assertEqual(merged[0].headline, "Best headline with high importance")

    def test_apply_merge_respects_max_clusters_and_fulltext_flag(self):
        articles_by_id = {}
        classified_by_id = {}
        clusters = []

        for i in range(5):
            aid = f"art_{i}"
            art = Article(id=aid, source=f"src_{i}", source_group="g", url=f"http://{i}",
                          title=f"Title {i}", summary_raw="", published_at="2026-11-03T10:00:00+07:00", fetched_at="")
            articles_by_id[aid] = art
            classified_by_id[aid] = {"id": aid, "importance": i + 1, "entities": [], "is_noise": False}
            c = Cluster(cluster_id=f"c-00{i+1}", headline=f"Title {i}", topics=["vimo"], article_ids=[aid], source_count=1)
            cluster.score(c, articles_by_id, classified_by_id, self.profile, self.now)
            clusters.append(c)

        # Profile with max_clusters = 2, digest_items = 1 -> fulltext_limit = 2
        limited_profile = {
            "max_clusters": 2,
            "digest_items": 1,
            "weights": self.profile["weights"],
        }

        merged = cluster.apply_merge(
            clusters,
            [],  # No merges
            articles_by_id,
            classified_by_id,
            limited_profile,
            self.now,
        )

        self.assertEqual(len(merged), 2)
        self.assertTrue(merged[0].needs_fulltext)
        self.assertTrue(merged[1].needs_fulltext)


if __name__ == "__main__":
    unittest.main()

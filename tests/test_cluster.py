from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import cluster
from fin_news.models import Article


def make_art(aid: str, source: str, title: str, pub_date: str = None) -> Article:
    return Article(
        id=aid,
        source=source,
        source_group="group",
        url=f"https://example.com/{aid}",
        title=title,
        summary_raw="Summary",
        published_at=pub_date,
        fetched_at="2026-11-03T12:00:00+07:00",
        fulltext=None,
    )


class TestCluster(unittest.TestCase):
    def test_cluster_groups_same_event_key_across_sources(self):
        a1 = make_art("1", "s1", "NHNN giảm lãi suất điều hành")
        a2 = make_art("2", "s2", "Ngân hàng Nhà nước hạ lãi suất điều hành")
        classified = [
            {"id": "1", "topics": ["ngan-hang"], "importance": 4, "event_key": "nhnn-giam-lai-suat", "is_noise": False},
            {"id": "2", "topics": ["ngan-hang"], "importance": 4, "event_key": "nhnn-giam-lai-suat", "is_noise": False},
        ]
        clusters = cluster.cluster([a1, a2], classified)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(set(clusters[0].article_ids), {"1", "2"})
        self.assertEqual(clusters[0].source_count, 2)

    def test_cluster_ignores_noise(self):
        a1 = make_art("1", "s1", "Tin kinh tế quan trọng")
        a2 = make_art("2", "s2", "Quảng cáo khoá học làm giàu")
        classified = [
            {"id": "1", "topics": ["ngan-hang"], "importance": 3, "event_key": "tin-kinh-te", "is_noise": False},
            {"id": "2", "topics": ["ngan-hang"], "importance": 0, "event_key": "quang-cao", "is_noise": True},
        ]
        clusters = cluster.cluster([a1, a2], classified)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].article_ids, ["1"])

    def test_source_count_counts_distinct_sources(self):
        a1 = make_art("1", "s1", "Bài 1")
        a2 = make_art("2", "s1", "Bài 2 từ cùng nguồn s1")
        classified = [
            {"id": "1", "topics": ["vi-mo"], "importance": 2, "event_key": "ev-1", "is_noise": False},
            {"id": "2", "topics": ["vi-mo"], "importance": 2, "event_key": "ev-1", "is_noise": False},
        ]
        clusters = cluster.cluster([a1, a2], classified)
        self.assertEqual(clusters[0].source_count, 1)

    def test_score_rewards_more_sources(self):
        profile = {
            "watchlist": [],
            "weights": {"max_importance": 1.0, "source_bonus": [0, 1.0, 2.0], "recency_bonus": 1.0, "watchlist_bonus": 1.5}
        }
        now = datetime.now(timezone.utc)
        pub_recent = (now - timedelta(hours=1)).isoformat()

        # Cluster 1: 1 source
        c1 = cluster.Cluster("c1", "T1", ["t1"], ["1"], source_count=1)
        art1 = make_art("1", "s1", "T1", pub_recent)
        cl1 = {"id": "1", "importance": 3, "entities": []}

        # Cluster 2: 4 sources
        c2 = cluster.Cluster("c2", "T2", ["t1"], ["2", "3", "4", "5"], source_count=4)
        art2 = make_art("2", "s2", "T2", pub_recent)
        cl2 = {"id": "2", "importance": 3, "entities": []}

        articles_map = {"1": art1, "2": art2, "3": art2, "4": art2, "5": art2}
        classified_map = {"1": cl1, "2": cl2, "3": cl2, "4": cl2, "5": cl2}

        score1 = cluster.score(c1, articles_map, classified_map, profile, now)
        score2 = cluster.score(c2, articles_map, classified_map, profile, now)
        # Score 2 has source bonus of 2.0 while score 1 has 0
        self.assertGreater(score2, score1)
        self.assertAlmostEqual(score2 - score1, 2.0)

    def test_score_watchlist_bonus(self):
        profile = {
            "watchlist": ["VIC", "Vingroup"],
            "weights": {"watchlist_bonus": 1.5}
        }
        now = datetime.now(timezone.utc)
        c = cluster.Cluster("c1", "Tiêu đề", ["doanh-nghiep"], ["1"], source_count=1)
        art = make_art("1", "s1", "Cổ phiếu VIC tăng trần")
        cl = {"id": "1", "importance": 3, "entities": ["VIC"]}
        score = cluster.score(c, {"1": art}, {"1": cl}, profile, now)

        # Baseline without match
        profile_no_match = {"watchlist": ["HPG"], "weights": {"watchlist_bonus": 1.5}}
        score_no_match = cluster.score(c, {"1": art}, {"1": cl}, profile_no_match, now)
        self.assertAlmostEqual(score - score_no_match, 1.5)

    def test_score_unknown_date_no_recency_bonus(self):
        profile = {"watchlist": [], "weights": {"recency_bonus": 1.0}}
        now = datetime.now(timezone.utc)
        c_nodate = cluster.Cluster("c1", "T", ["t"], ["1"], source_count=1)
        art_nodate = make_art("1", "s1", "T", pub_date=None)
        cl = {"id": "1", "importance": 3, "entities": []}

        score_nodate = cluster.score(c_nodate, {"1": art_nodate}, {"1": cl}, profile, now)
        # Importance 3, source 1 -> 0 bonus, recency -> 0 bonus, watchlist -> 0
        self.assertAlmostEqual(score_nodate, 3.0)

    def test_select_limits_to_max_clusters_and_marks_fulltext(self):
        profile = {"max_clusters": 5, "digest_items": 2}  # fulltext count = 2 * 2 = 4
        clusters = [
            cluster.Cluster(f"c{i}", f"T{i}", ["t"], [str(i)], score=float(10 - i))
            for i in range(10)
        ]
        selected = cluster.select(clusters, profile)
        self.assertEqual(len(selected), 5)
        # Top 4 have needs_fulltext=True
        self.assertTrue(selected[0].needs_fulltext)
        self.assertTrue(selected[1].needs_fulltext)
        self.assertTrue(selected[2].needs_fulltext)
        self.assertTrue(selected[3].needs_fulltext)
        # 5th does not
        self.assertFalse(selected[4].needs_fulltext)


if __name__ == "__main__":
    unittest.main()

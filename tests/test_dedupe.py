from datetime import datetime
from pathlib import Path
import sys
import unittest

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import dedupe
from fin_news.models import Article, article_id


def make_art(
    id_s: str,
    title: str,
    url: str,
    source: str = "cafef",
    summary: str = "Summary",
    pub_date: str = "2026-11-03T10:00:00+07:00",
) -> Article:
    return Article(
        id=article_id(url),
        source=source,
        source_group="finance",
        url=url,
        title=title,
        summary_raw=summary,
        published_at=pub_date,
        fetched_at="2026-11-03T11:00:00+07:00",
        fulltext=None,
    )


class TestDedupe(unittest.TestCase):
    def test_same_url_with_utm_is_duplicate(self):
        a1 = make_art("1", "Tin tức tài chính", "https://example.com/art1?utm_source=facebook&utm_medium=cpc")
        a2 = make_art("2", "Tin tức tài chính", "https://example.com/art1")
        res = dedupe.dedupe([a1, a2])
        self.assertEqual(len(res), 1)

    def test_near_identical_titles_across_sources_merge(self):
        a1 = make_art("1", "Giá vàng SJC hôm nay tăng mạnh vượt 90 triệu đồng", "https://source1.com/a1", source="s1", pub_date="2026-11-03T09:00:00+07:00")
        a2 = make_art("2", "Giá vàng SJC hôm nay tăng mạnh vượt 90 triệu đồng/lượng", "https://source2.com/a2", source="s2", pub_date="2026-11-03T09:30:00+07:00")
        res = dedupe.dedupe([a1, a2], threshold=0.85)
        self.assertEqual(len(res), 1)
        # Keeps earliest published
        self.assertEqual(res[0].source, "s1")

    def test_different_events_with_similar_words_are_kept(self):
        a1 = make_art("1", "Vietcombank tăng lãi suất huy động lên 6%", "https://s1.com/1", source="s1")
        a2 = make_art("2", "Techcombank giảm lãi suất cho vay xuống 7%", "https://s2.com/2", source="s2")
        res = dedupe.dedupe([a1, a2], threshold=0.88)
        self.assertEqual(len(res), 2)

    def test_accent_insensitive_title_match(self):
        a1 = make_art("1", "Thị trường chứng khoán hôm nay khởi sắc", "https://s1.com/1", pub_date="2026-11-03T08:00:00+07:00")
        a2 = make_art("2", "Thi truong chung khoan hom nay khoi sac", "https://s2.com/2", pub_date="2026-11-03T08:30:00+07:00")
        res = dedupe.dedupe([a1, a2], threshold=0.88)
        self.assertEqual(len(res), 1)

    def test_prefilter_drops_unrelated_from_mixed_source_only(self):
        topics_cfg = {
            "topics": {
                "ngan-hang": {"keywords": ["lãi suất", "ngân hàng"]},
                "chung-khoan": {"keywords": ["chứng khoán", "cổ phiếu"]},
            }
        }
        mixed = {"vneconomy"}
        a_related = make_art("1", "Ngân hàng tăng vốn điều lệ", "https://vneconomy.vn/1", source="vneconomy")
        a_unrelated = make_art("2", "Bí quyết làm đẹp mùa đông cho phụ nữ", "https://vneconomy.vn/2", source="vneconomy", summary="Chăm sóc da")

        res = dedupe.prefilter([a_related, a_unrelated], topics_cfg, mixed)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0].id, a_related.id)

    def test_prefilter_keeps_everything_from_non_mixed_source(self):
        topics_cfg = {
            "topics": {
                "ngan-hang": {"keywords": ["lãi suất"]},
            }
        }
        mixed = {"vneconomy"}
        a_pure = make_art("1", "Tin tức bất kỳ từ nguồn chuyên ngành", "https://cafef.vn/1", source="cafef-chungkhoan")
        res = dedupe.prefilter([a_pure], topics_cfg, mixed)
        self.assertEqual(len(res), 1)


if __name__ == "__main__":
    unittest.main()

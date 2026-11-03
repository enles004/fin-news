import html
from pathlib import Path
import re
import sys
import unittest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news.extract import extract_article_text, extract_with_tier, get_title_words


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "pages"

    def test_every_source_fixture_yields_clean_article_text(self):
        # The saved news pages are third-party content and are git-ignored, so
        # a fresh clone does not have them; this test only runs where they exist.
        fixture_files = sorted(self.fixtures_dir.glob("*.html")) if self.fixtures_dir.is_dir() else []
        if not fixture_files:
            self.skipTest("tests/fixtures/pages is not present (git-ignored third-party pages)")
        self.assertEqual(len(fixture_files), 15, "Expected 15 source page fixtures")

        forbidden = ["function(", "var ", "@context", "dataLayer", "cmsConfig"]

        for fixture_file in fixture_files:
            source_id = fixture_file.stem
            html_content = fixture_file.read_text(encoding="utf-8")

            m = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
            title = html.unescape(m.group(1)).strip() if m else ""

            text = extract_article_text(html_content, title=title, max_chars=3500)

            self.assertGreaterEqual(
                len(text), 300,
                f"Source {source_id} yielded text shorter than 300 characters ({len(text)} chars)"
            )
            self.assertLessEqual(
                len(text), 3500,
                f"Source {source_id} yielded text longer than 3500 characters ({len(text)} chars)"
            )

            for bad in forbidden:
                self.assertNotIn(
                    bad, text,
                    f"Source {source_id} output contains forbidden substring '{bad}'"
                )

            # At least two non-trivial words from the page's <title> must appear in output
            title_words = get_title_words(title)
            text_lower = text.lower()
            matched_words = [w for w in title_words if w in text_lower]
            self.assertGreaterEqual(
                len(matched_words), min(2, len(title_words)),
                f"Source {source_id} output does not contain at least 2 non-trivial words from title. "
                f"Title: '{title}', Title words: {title_words}, Matched: {matched_words}"
            )

    def test_json_ld_article_body_preferred_when_present(self):
        json_ld_body = (
            "Nội dung toàn văn bài báo từ JSON-LD của bài viết. "
            "Đây là nội dung chính thống được cung cấp qua schema NewsArticle của trang báo điện tử. "
            "Dữ liệu này được ưu tiên hàng đầu theo thuật toán bóc tách dữ liệu tin tức tài chính. "
            "Đoạn văn này dài hơn hai trăm ký tự để đáp ứng ngưỡng tối thiểu của bộ bóc tách."
        )
        article_elem_text = (
            "Nội dung từ thẻ article HTML thông thường. "
            "Đoạn văn này cũng dài hơn hai trăm ký tự để kiểm tra độ ưu tiên giữa các ứng viên khác nhau. "
            "Nếu JSON-LD có mặt và hợp lệ thì thẻ article này không được chọn làm kết quả bóc tách."
        )

        sample_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Tiêu đề bài báo tài chính thử nghiệm</title>
    <script type="application/ld+json">
    {{
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "Tiêu đề bài báo tài chính thử nghiệm",
        "articleBody": "{json_ld_body}"
    }}
    </script>
</head>
<body>
    <article>
        <p>{article_elem_text}</p>
    </article>
</body>
</html>"""

        output = extract_article_text(sample_html)
        self.assertIn("Nội dung toàn văn bài báo từ JSON-LD", output)
        self.assertNotIn("Nội dung từ thẻ article HTML thông thường", output)

    def test_article_element_used_when_no_json_ld(self):
        article_text_p1 = (
            "Đoạn thứ nhất trong thẻ article của bài báo tài chính. "
            "Đây là phần mở đầu mô tả diễn biến thị trường và các số liệu thống kê liên quan."
        )
        article_text_p2 = (
            "Đoạn thứ hai trong thẻ article tiếp tục phân tích sâu hơn về nguyên nhân biến động giá. "
            "Các chuyên gia tài chính đánh giá xu hướng này sẽ còn tiếp diễn trong thời gian tới."
        )
        step3_text = (
            "Nội dung từ thẻ div detail-content nằm bên ngoài. "
            "Thẻ này có độ ưu tiên thấp hơn thẻ article theo quy định của thuật toán bóc tách bài viết."
        )

        sample_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Diễn biến thị trường tài chính và giá vàng</title>
</head>
<body>
    <article>
        <p>{article_text_p1}</p>
        <p>{article_text_p2}</p>
    </article>
    <div class="detail-content">
        <p>{step3_text}</p>
    </div>
</body>
</html>"""

        output = extract_article_text(sample_html, title="Diễn biến thị trường tài chính và giá vàng")
        self.assertIn("Đoạn thứ nhất trong thẻ article", output)
        self.assertIn("Đoạn thứ hai trong thẻ article", output)
        self.assertNotIn("Nội dung từ thẻ div detail-content", output)

    def test_paragraph_density_fallback(self):
        p_long1 = "Đoạn văn dài hơn bốn mươi ký tự thứ nhất nhằm kiểm tra mật độ đoạn văn trong bộ bóc tách tin tức."
        p_long2 = "Đoạn văn dài hơn bốn mươi ký tự thứ hai cung cấp thêm thông tin chi tiết về sự kiện kinh tế."
        p_long3 = "Đoạn văn dài hơn bốn mươi ký tự thứ ba tiếp tục bổ sung số liệu phân tích tài chính thị trường."

        p_short = "Đoạn văn ngắn."

        sample_html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Phân tích mật độ đoạn văn tài chính</title>
</head>
<body>
    <div class="sidebar-box">
        <p>{p_short}</p>
        <p>{p_short}</p>
    </div>
    <div class="random-wrapper">
        <p>{p_long1}</p>
        <p>{p_long2}</p>
        <p>{p_long3}</p>
    </div>
</body>
</html>"""

        output = extract_article_text(sample_html, title="Phân tích mật độ đoạn văn tài chính")
        self.assertIn(p_long1, output)
        self.assertIn(p_long2, output)
        self.assertNotIn(p_short, output)

    def test_script_and_style_content_never_returned(self):
        body_p1 = "Nội dung bài viết hợp lệ cần được trích xuất đầy đủ và chính xác từ trang web."
        body_p2 = "Phần nội dung này phân tích số liệu tài chính phục vụ người dùng theo dõi thị trường."
        body_p3 = "Thêm đoạn văn bản này để đảm bảo tổng độ dài văn bản vượt qua ngưỡng hai trăm ký tự tối thiểu."

        sample_html = f"""<!DOCTYPE html>
<html>
<head>
    <style>body {{ background: #fff; }} .ads {{ display: none; }}</style>
    <script>
        var cmsConfig = {{ api: "https://example.com/api" }};
        function() {{ window.dataLayer.push({{'event': 'pageview'}}); }}
    </script>
</head>
<body>
    <article>
        <script>var innerScript = true; function() {{}};</script>
        <style>.inner {{ color: red; }}</style>
        <p>{body_p1}</p>
        <p>{body_p2}</p>
        <p>{body_p3}</p>
        <div class="related-news">
            <p>Tin tức liên quan không được xuất hiện trong kết quả toàn văn.</p>
        </div>
        <div class="comment-box">
            <p>Bình luận của độc giả cũng phải bị loại bỏ hoàn toàn.</p>
        </div>
    </article>
</body>
</html>"""

        output = extract_article_text(sample_html)
        self.assertIn(body_p1, output)
        self.assertIn(body_p2, output)
        self.assertIn(body_p3, output)
        self.assertNotIn("cmsConfig", output)
        self.assertNotIn("dataLayer", output)
        self.assertNotIn("function(", output)
        self.assertNotIn("var ", output)
        self.assertNotIn("color: red", output)
        self.assertNotIn("Tin tức liên quan", output)
        self.assertNotIn("Bình luận của độc giả", output)

    def test_returns_empty_when_nothing_usable(self):
        sample_html = """<!DOCTYPE html>
<html>
<head><title>Trang rỗng</title></head>
<body>
    <p>Quá ngắn.</p>
</body>
</html>"""
        output = extract_article_text(sample_html)
        self.assertEqual(output, "")

    def test_cut_at_paragraph_boundary_within_max_chars(self):
        # Paragraphs of length 150 each
        p1 = "A" * 150
        p2 = "B" * 150
        p3 = "C" * 150

        # p1 (150) + "\n\n" (2) + p2 (150) = 302 chars
        # Adding p3 (+2 + 150) would reach 454 chars > 350 max_chars
        sample_html = f"""<!DOCTYPE html>
<html>
<head><title>Kiểm tra cắt đoạn văn</title></head>
<body>
    <article>
        <p>{p1}</p>
        <p>{p2}</p>
        <p>{p3}</p>
    </article>
</body>
</html>"""

        output = extract_article_text(sample_html, max_chars=350)
        self.assertLessEqual(len(output), 350)
        self.assertIn(p1, output)
        self.assertIn(p2, output)
        self.assertNotIn(p3, output)

    def test_extract_with_tier_reports_each_tier(self):
        long_p1 = "Nội dung bài viết tài chính dài hơn một trăm ký tự kiểm tra các tầng bóc tách khác nhau của hệ thống fin-news."
        long_p2 = "Đoạn văn thứ hai bổ sung thêm nhiều dữ liệu phân tích số liệu thị trường để vượt qua ngưỡng hai trăm ký tự."

        # 1. json-ld
        html_jsonld = f"""<html><head><script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{long_p1} {long_p2}"}}
        </script></head><body></body></html>"""
        txt, tier = extract_with_tier(html_jsonld)
        self.assertEqual(tier, "json-ld")
        self.assertGreater(len(txt), 200)

        # 2. article
        html_article = f"""<html><body><article><p>{long_p1}</p><p>{long_p2}</p></article></body></html>"""
        txt, tier = extract_with_tier(html_article)
        self.assertEqual(tier, "article")
        self.assertGreater(len(txt), 200)

        # 3. hint
        html_hint = f"""<html><body><div class="article-content"><p>{long_p1}</p><p>{long_p2}</p></div></body></html>"""
        txt, tier = extract_with_tier(html_hint)
        self.assertEqual(tier, "hint")
        self.assertGreater(len(txt), 200)

        # 4. density
        html_density = f"""<html><body><div class="custom-unknown-container"><p>{long_p1}</p><p>{long_p2}</p></div></body></html>"""
        txt, tier = extract_with_tier(html_density)
        self.assertEqual(tier, "density")
        self.assertGreater(len(txt), 200)

        # 5. empty/short
        txt, tier = extract_with_tier("<html><body><p>Ngắn</p></body></html>")
        self.assertEqual(txt, "")
        self.assertEqual(tier, "")

    def test_hints_are_tried_before_builtin_hints(self):
        p_custom = "Đoạn văn từ container tùy biến với gợi ý trích xuất riêng biệt cần được ưu tiên xử lý trước." * 3
        p_builtin = "Đoạn văn từ container mặc định có class article-body thông thường được xử lý sau." * 3

        html = f"""<html><body>
        <div class="my-custom-box"><p>{p_custom}</p></div>
        <div class="article-body"><p>{p_builtin}</p></div>
        </body></html>"""

        txt, tier = extract_with_tier(html, hints=("my-custom-box",))
        self.assertEqual(tier, "hint")
        self.assertIn("gợi ý trích xuất riêng biệt", txt)
        self.assertNotIn("thông thường được xử lý sau", txt)

    def test_extract_article_text_wrapper_unchanged(self):
        long_p = "Nội dung bài viết tài chính thử nghiệm để kiểm tra tính toàn vẹn của wrapper extract_article_text so với extract_with_tier." * 3
        html = f"""<html><body><article><p>{long_p}</p></article></body></html>"""
        wrapper_text = extract_article_text(html)
        tier_text, tier = extract_with_tier(html)
        self.assertEqual(wrapper_text, tier_text)
        self.assertEqual(tier, "article")


if __name__ == "__main__":
    unittest.main()

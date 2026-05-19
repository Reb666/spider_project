import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dangdang_scrapy.parsers import parse_price, parse_rating_from_style, parse_review_count, parse_detail_rating, parse_isbn


class TestParsePrice:
    def test_normal(self):
        assert parse_price("¥35.70") == 35.7
        assert parse_price("288.00") == 288.0
        assert parse_price("0.01") == 0.01

    def test_with_prefix(self):
        assert parse_price("¥26.1") == 26.1
        assert parse_price("￥100") == 100.0

    def test_none_and_empty(self):
        assert parse_price(None) is None
        assert parse_price("") is None

    def test_dirty(self):
        assert parse_price("约¥35.70元起") == 35.7


class TestParseRatingFromStyle:
    def test_normal(self):
        assert parse_rating_from_style("width:90.4%") == 90.4
        assert parse_rating_from_style("width:100%") == 100.0
        assert parse_rating_from_style("width: 50%") == 50.0

    def test_none(self):
        assert parse_rating_from_style(None) is None
        assert parse_rating_from_style("") is None

    def test_no_match(self):
        assert parse_rating_from_style("height:90%") is None


class TestParseReviewCount:
    def test_normal(self):
        assert parse_review_count("35672条评论") == 35672
        assert parse_review_count("469028") == 469028

    def test_none_and_empty(self):
        assert parse_review_count(None) is None
        assert parse_review_count("") is None


class TestParseDetailRating:
    def test_normal_html(self):
        html = '<span class="star_box"><span class="star" style="width:96.8%"></span></span><a id="comm_num_down">1525</a>条评论'
        r, p = parse_detail_rating(html)
        assert r == 96.8
        assert p == 1525

    def test_no_rating(self):
        html = "<html><body>无评分</body></html>"
        r, p = parse_detail_rating(html)
        assert r is None
        assert p is None

    def test_zero_rating(self):
        html = '<span class="star_box"><span class="star" style="width:0%"></span></span><a id="comm_num_down">0</a>'
        r, p = parse_detail_rating(html)
        assert r == 0.0
        assert p == 0


class TestParseIsbn:
    def test_normal_13_digit(self):
        assert parse_isbn("国际标准书号ISBN：9787572614736") == "9787572614736"

    def test_colon_alternative(self):
        assert parse_isbn("国际标准书号ISBN:9787572614736") == "9787572614736"

    def test_10_digit(self):
        assert parse_isbn("国际标准书号ISBN：7532767180") == "7532767180"

    def test_none(self):
        assert parse_isbn("<html>no isbn</html>") is None

    def test_empty(self):
        assert parse_isbn("") is None

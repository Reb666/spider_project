import os
import scrapy
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
from dangdang_scrapy.items import BookItem
from dangdang_scrapy.parsers import parse_price, parse_rating_from_style, parse_review_count
from dangdang_scrapy.session import get_user_data_dir

load_dotenv()
USE_PW = os.environ.get("DANGDANG_USE_PLAYWRIGHT", "").lower() in ("1", "true", "yes")


def _normalize_url(raw, response):
    """规范化商品链接：丢弃跳转/广告链接，归一化 product.dangdang.com 链接"""
    if not raw:
        return None
    if raw.startswith(("javascript:", "mailto:", "#")):
        return None
    url = ("http:" + raw) if raw.startswith("//") else response.urljoin(raw)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    # 只保留 product.dangdang.com 的商品详情页
    if "product.dangdang.com" not in hostname:
        return None
    # 丢弃 tracking / jump / 广告链接
    if "jump.php" in parsed.path:
        return None
    # 去掉追踪参数，保留纯净链接
    clean = urlunparse((parsed.scheme, hostname, parsed.path, "", "", ""))
    return clean


def _request_meta():
    meta = {}
    if USE_PW:
        from scrapy_playwright.page import PageMethod
        meta["playwright"] = True
        meta["playwright_context_kwargs"] = {
            "user_data_dir": str(get_user_data_dir()),
        }
        meta["playwright_page_methods"] = [
            PageMethod(
                "wait_for_selector",
                "ul.bigimg, div.cloth_good_sort, span.search_now_price, span.d_price",
                timeout=15000,
            ),
        ]
    return meta


class DangdangSpider(scrapy.Spider):
    name = "dangdang"
    allowed_domains = ["category.dangdang.com", "dangdang.com", "product.dangdang.com"]

    start_urls = [
        ("cp01.01.01.00.00.00.html", "标准"),
        ("cp01.01.02.00.00.00.html", "标准"),
        ("cp01.01.03.00.00.00.html", "标准"),
        ("cp01.01.04.00.00.00.html", "标准"),
        ("cp01.01.05.00.00.00.html", "标准"),
        ("cp01.02.01.00.00.00.html", "促销"),
        ("cp01.02.02.00.00.00.html", "促销"),
        ("cp01.02.03.00.00.00.html", "促销"),
        ("cp01.02.04.00.00.00.html", "促销"),
        ("cp01.02.05.00.00.00.html", "促销"),
        ("cp01.02.06.00.00.00.html", "促销"),
        ("cp01.02.07.00.00.00.html", "促销"),
        ("cp01.02.08.00.00.00.html", "促销"),
        ("cp01.02.09.00.00.00.html", "促销"),
        ("cp01.02.10.00.00.00.html", "促销"),
        ("cp01.03.01.00.00.00.html", "促销"),
        ("cp01.03.02.00.00.00.html", "促销"),
        ("cp01.03.04.00.00.00.html", "促销"),
        ("cp01.04.01.00.00.00.html", "促销"),
        ("cp01.04.02.00.00.00.html", "促销"),
        ("cp01.05.01.00.00.00.html", "促销"),
        ("cp01.07.01.00.00.00.html", "促销"),
    ]

    def start_requests(self):
        for path, layout in self.start_urls:
            url = f"http://category.dangdang.com/{path}"
            cb = self.parse_standard if layout == "标准" else self.parse_promotional
            yield scrapy.Request(
                url=url,
                callback=cb,
                meta={"category": "图书", **_request_meta()},
            )

    def parse_standard(self, response):
        for item in self._parse_standard_items(response):
            yield item
        yield from self._follow_next(response, self.parse_standard)

    def parse_promotional(self, response):
        for item in self._parse_promo_items(response):
            yield item
        yield from self._follow_next(response, self.parse_promotional)

    def _parse_standard_items(self, response):
        category = response.meta.get("category", "图书")
        for book in response.css("ul.bigimg li"):
            item = BookItem()
            item["name"] = book.css("a.pic::attr(title)").get() or ""
            item["detail_url"] = _normalize_url(book.css("a.pic::attr(href)").get(), response)
            item["author"] = book.css("p.search_book_author a[name='itemlist-author']::text").get("").strip()
            item["publisher"] = book.css("p.search_book_author a[name='P_cbs']::text").get("").strip()
            item["price"] = parse_price(book.css("span.search_now_price::text").get())
            item["original_price"] = parse_price(book.css("span.search_pre_price::text").get())
            item["rating"] = parse_rating_from_style(book.css("span.search_star_black span::attr(style)").get())
            item["rating_people"] = parse_review_count(book.css("a.search_comment_num::text").get())
            item["sales"] = None
            item["category"] = category
            if item["name"] and item["detail_url"]:
                yield item

    def _parse_promo_items(self, response):
        category = response.meta.get("category", "图书")
        for book in response.css("div.cloth_good_sort li"):
            item = BookItem()
            item["name"] = book.css("a.name::text").get("").strip() or None
            item["detail_url"] = _normalize_url(book.css("a.pic::attr(href)").get(), response)
            item["author"] = ""
            item["price"] = parse_price(book.css("span.d_price::text").get())
            orig_els = book.css("p.price_p i.m_price")
            item["original_price"] = parse_price(orig_els[-1].css("::text").get()) if len(orig_els) > 1 else None
            item["rating"] = None
            item["rating_people"] = None
            item["sales"] = None
            item["category"] = category
            if item["name"] and item["detail_url"]:
                yield item

    def _follow_next(self, response, callback):
        next_page = response.css("li.next a::attr(href), a.next::attr(href)").get()
        if next_page and next_page not in ("javascript:;", "#"):
            next_url = response.urljoin(next_page)
            self.logger.info(f"Following next: {next_url}")
            yield scrapy.Request(
                url=next_url,
                callback=callback,
                meta={"category": response.meta.get("category", "图书"), **_request_meta()},
            )

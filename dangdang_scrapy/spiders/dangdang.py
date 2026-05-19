import os
import scrapy
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
from dangdang_scrapy.items import BookItem
from dangdang_scrapy.parsers import parse_price, parse_rating_from_style, parse_review_count

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
    if "product.dangdang.com" not in hostname:
        return None
    if "jump.php" in parsed.path:
        return None
    clean = urlunparse((parsed.scheme, hostname, parsed.path, "", "", ""))
    return clean


def _request_meta():
    meta = {}
    if USE_PW:
        from scrapy_playwright.page import PageMethod
        meta["playwright"] = True
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

    # 带筛选时连续空页上限（避免无限制翻页）
    MAX_EMPTY_PAGES = 3
    # 单次爬取最大翻页数（防止无限制爬取）
    MAX_PAGES = 100

    def __init__(self, name_filter=None, author_filter=None, publisher_filter=None,
                 rating_min=None, rating_max=None, price_min=None, price_max=None,
                 people_min=None, max_items=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name_filter = (name_filter or "").strip().lower() or None
        self.author_filter = (author_filter or "").strip().lower() or None
        self.publisher_filter = (publisher_filter or "").strip().lower() or None
        self.rating_min = float(rating_min) if rating_min else None
        self.rating_max = float(rating_max) if rating_max else None
        self.price_min = float(price_min) if price_min else None
        self.price_max = float(price_max) if price_max else None
        self.people_min = int(people_min) if people_min else None
        self.max_items = int(max_items) if max_items else None
        self._scraped_count = 0
        self._page_count = 0
        self._consecutive_empty = 0

    def _has_active_filters(self):
        """是否有任何爬取筛选条件"""
        return bool(
            self.name_filter or self.author_filter or self.publisher_filter
            or self.rating_min is not None or self.rating_max is not None
            or self.price_min is not None or self.price_max is not None
            or self.people_min is not None
        )

    def _limit_reached(self):
        return self.max_items and self._scraped_count >= self.max_items

    def _should_follow_next(self, found_on_page):
        """判断是否应该继续翻到下一页"""
        if self._limit_reached():
            return False
        if self._page_count >= self.MAX_PAGES:
            return False
        if self._has_active_filters():
            if not found_on_page:
                self._consecutive_empty += 1
                if self._consecutive_empty >= self.MAX_EMPTY_PAGES:
                    return False
            else:
                self._consecutive_empty = 0
        return True

    def _passes_filter(self, item):
        if self.name_filter and self.name_filter not in (item.get("name") or "").lower():
            return False
        if self.author_filter and self.author_filter not in (item.get("author") or "").lower():
            return False
        if self.publisher_filter and self.publisher_filter not in (item.get("publisher") or "").lower():
            return False
        if self.rating_min is not None:
            if item.get("rating") is None or item["rating"] < self.rating_min:
                return False
        if self.rating_max is not None:
            if item.get("rating") is None or item["rating"] > self.rating_max:
                return False
        if self.price_min is not None:
            if item.get("price") is None or item["price"] < self.price_min:
                return False
        if self.price_max is not None:
            if item.get("price") is None or item["price"] > self.price_max:
                return False
        if self.people_min is not None:
            if item.get("rating_people") is None or item["rating_people"] < self.people_min:
                return False
        return True

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
            if self._limit_reached():
                break
            url = f"http://category.dangdang.com/{path}"
            cb = self.parse_standard if layout == "标准" else self.parse_promotional
            yield scrapy.Request(
                url=url,
                callback=cb,
                meta={"category": "图书", **_request_meta()},
            )

    def parse_standard(self, response):
        self._page_count += 1
        found = False
        for item in self._parse_standard_items(response):
            found = True
            yield item
        if self._should_follow_next(found):
            yield from self._follow_next(response, self.parse_standard)

    def parse_promotional(self, response):
        self._page_count += 1
        found = False
        for item in self._parse_promo_items(response):
            found = True
            yield item
        if self._should_follow_next(found):
            yield from self._follow_next(response, self.parse_promotional)

    def _parse_standard_items(self, response):
        category = response.meta.get("category", "图书")
        for book in response.css("ul.bigimg li"):
            if self._limit_reached():
                return
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
            if item["name"] and item["detail_url"] and self._passes_filter(item):
                self._scraped_count += 1
                yield item

    def _parse_promo_items(self, response):
        category = response.meta.get("category", "图书")
        for book in response.css("div.cloth_good_sort li"):
            if self._limit_reached():
                return
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
            if item["name"] and item["detail_url"] and self._passes_filter(item):
                self._scraped_count += 1
                yield item

    def _follow_next(self, response, callback):
        next_page = response.css("li.next a::attr(href), a.next::attr(href)").get()
        if next_page and next_page not in ("javascript:;", "#"):
            next_url = response.urljoin(next_page)
            yield scrapy.Request(
                url=next_url,
                callback=callback,
                meta={"category": response.meta.get("category", "图书"), **_request_meta()},
            )

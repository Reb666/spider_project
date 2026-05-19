import os
import scrapy
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
from dangdang_scrapy.items import BookItem
from dangdang_scrapy.parsers import parse_price, parse_rating_from_style, parse_review_count
from dangdang_scrapy.session import get_user_data_dir

load_dotenv()
USE_PW = os.environ.get("DANGDANG_USE_PLAYWRIGHT", "").lower() in ("1", "true", "yes")
_MAX_PER_L3 = 50


def _normalize_url(raw, response):
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
    allowed_domains = ["category.dangdang.com", "dangdang.com", "product.dangdang.com", "static.dangdang.com"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_l2 = set()
        self._seen_l3 = set()

    def start_requests(self):
        yield scrapy.Request(
            url="http://category.dangdang.com/cp01.01.01.00.00.00.html",
            callback=self.parse_l2_list,
            meta={"category": "图书", **_request_meta()},
        )

    def parse_l2_list(self, response):
        """Discover all second-level categories from breadcrumb, then crawl each."""
        list_products = response.css("#breadcrumb .select_frame > .list_product")
        if not list_products:
            self.logger.warning("No category dropdown found, falling back to direct parse")
            yield from self._parse_items(response, None, None, None)
            return

        # First list_product = all l2 categories
        l1_name = response.css("#breadcrumb a[dd_name='面包屑1级']::text").get("").strip() or "图书"
        for a in list_products[0].css("a"):
            href = a.attrib.get("href", "")
            if "/cp" not in href:
                continue
            l2_name = a.attrib.get("title", a.css("::text").get("")).strip()
            url = response.urljoin(href)
            if url in self._seen_l2:
                continue
            self._seen_l2.add(url)
            yield scrapy.Request(
                url=url,
                callback=self.parse_l3_list,
                meta={"category": l1_name, "l2_name": l2_name, **_request_meta()},
            )

    def parse_l3_list(self, response):
        """Discover third-level categories from breadcrumb, or parse items directly."""
        l2_name = response.meta.get("l2_name", "")
        list_products = response.css("#breadcrumb .select_frame > .list_product")

        if len(list_products) >= 2:
            # Second list_product = l3 categories under this l2
            l1_name = response.meta.get("category", "图书")
            for a in list_products[1].css("a"):
                href = a.attrib.get("href", "")
                if "/cp" not in href:
                    continue
                l3_name = a.attrib.get("title", a.css("::text").get("")).strip()
                url = response.urljoin(href)
                key = (l2_name, l3_name)
                if key in self._seen_l3:
                    continue
                self._seen_l3.add(key)
                yield scrapy.Request(
                    url=url,
                    callback=self.parse_category,
                    meta={
                        "category": l1_name,
                        "l2_name": l2_name,
                        "l3_name": l3_name,
                        "scraped": 0,
                        **_request_meta(),
                    },
                )
        else:
            # No l3 subcategories — crawl this l2 page directly
            yield scrapy.Request(
                url=response.url,
                callback=self.parse_category,
                meta={
                    "category": response.meta.get("category", "图书"),
                    "l2_name": l2_name,
                    "l3_name": "",
                    "scraped": 0,
                    **_request_meta(),
                },
                dont_filter=True,
            )

    def parse_category(self, response):
        l1_name = response.meta.get("category", "图书")
        l2_name = response.meta.get("l2_name", "")
        l3_name = response.meta.get("l3_name", "")
        scraped = response.meta.get("scraped", 0)
        limit = _MAX_PER_L3

        for item in self._parse_standard_items(response, l1_name, l2_name, l3_name):
            if scraped >= limit:
                break
            yield item
            scraped += 1

        # Follow next page if under limit
        if scraped < limit:
            next_page = response.css("li.next a::attr(href), a.next::attr(href)").get()
            if next_page and next_page not in ("javascript:;", "#"):
                next_url = response.urljoin(next_page)
                yield scrapy.Request(
                    url=next_url,
                    callback=self.parse_category,
                    meta={
                        "category": l1_name,
                        "l2_name": l2_name,
                        "l3_name": l3_name,
                        "scraped": scraped,
                        **_request_meta(),
                    },
                )

    def _parse_items(self, response, l1_name, l2_name, l3_name):
        """Parse items from either standard or promotional layout."""
        books = response.css("ul.bigimg li")
        if books:
            yield from self._parse_standard_items(response, l1_name, l2_name, l3_name, books)
        else:
            yield from self._parse_promo_items(response, l1_name, l2_name, l3_name)

    def _parse_standard_items(self, response, l1_name, l2_name, l3_name, books=None):
        if books is None:
            books = response.css("ul.bigimg li")
        for book in books:
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
            item["category"] = l1_name or "图书"
            item["isbn"] = None
            item["category_l1_name"] = l1_name or "图书"
            item["category_l2_name"] = l2_name
            item["category_l3_name"] = l3_name
            if item["name"] and item["detail_url"]:
                yield item

    def _parse_promo_items(self, response, l1_name, l2_name, l3_name):
        for book in response.css("div.cloth_good_sort li"):
            item = BookItem()
            item["name"] = book.css("a.name::text").get("").strip() or None
            item["detail_url"] = _normalize_url(book.css("a.pic::attr(href)").get(), response)
            item["author"] = None
            item["price"] = parse_price(book.css("span.d_price::text").get())
            orig_els = book.css("p.price_p i.m_price")
            item["original_price"] = parse_price(orig_els[-1].css("::text").get()) if len(orig_els) > 1 else None
            item["rating"] = None
            item["rating_people"] = None
            item["sales"] = None
            item["category"] = l1_name or "图书"
            item["isbn"] = None
            item["category_l1_name"] = l1_name or "图书"
            item["category_l2_name"] = l2_name
            item["category_l3_name"] = l3_name
            if item["name"] and item["detail_url"]:
                yield item

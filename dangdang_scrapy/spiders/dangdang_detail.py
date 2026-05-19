import os
import re
import scrapy
from dotenv import load_dotenv
from dangdang_scrapy.db import get_engine
from dangdang_scrapy.parsers import parse_detail_rating, parse_isbn
from dangdang_scrapy.session import get_user_data_dir
from sqlalchemy import text

load_dotenv()
USE_PW = os.environ.get("DANGDANG_USE_PLAYWRIGHT", "").lower() in ("1", "true", "yes")


class DangdangDetailSpider(scrapy.Spider):
    name = "dangdang_detail"
    allowed_domains = ["product.dangdang.com", "dangdang.com"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 3,
        "DOWNLOAD_DELAY": 2.0,
        "RETRY_TIMES": 2,
        "ITEM_PIPELINES": {},
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.engine = get_engine()
        self.updated = 0
        self.skipped = 0
        self.http_errors = 0
        self.no_rating = 0
        self._batch = []

    def start_requests(self):
        urls = self._fetch_pending()
        self.logger.info(f"Fetched {len(urls)} URLs")
        for bid, detail_url in urls:
            meta = {"id": bid, "detail_url": detail_url}
            if USE_PW:
                from scrapy_playwright.page import PageMethod
                meta["playwright"] = True
                meta["playwright_context_kwargs"] = {
                    "user_data_dir": str(get_user_data_dir()),
                }
                meta["playwright_page_methods"] = [
                    PageMethod("wait_for_selector", "#comm_num_down, span.star", timeout=5000),
                    PageMethod("wait_for_timeout", 500),
                ]
            yield scrapy.Request(url=detail_url, callback=self.parse, meta=meta, errback=self.on_error)

    def _fetch_pending(self):
        sql = """SELECT id, detail_url FROM books
                 WHERE detail_url LIKE '%product.dangdang.com%'
                   AND (rating IS NULL OR rating = 0
                        OR rating_people IS NULL OR rating_people = 0
                        OR isbn IS NULL OR isbn = '')
                 ORDER BY id"""
        with self.engine.connect() as conn:
            return [(row[0], row[1]) for row in conn.execute(text(sql))]

    def parse(self, response):
        bid = response.meta["id"]
        rating, people = parse_detail_rating(response.text)
        if rating is None and people is None:
            self.no_rating += 1
        isbn = parse_isbn(response.text)
        cat_a = response.css("#detail-category-path a::text")
        l1_name = cat_a[0].get("").strip() if len(cat_a) > 0 else None
        l2_name = cat_a[1].get("").strip() if len(cat_a) > 1 else None
        l3_name = cat_a[2].get("").strip() if len(cat_a) > 2 else None
        self._batch.append((bid, rating, people, isbn, l1_name, l2_name, l3_name))
        if len(self._batch) >= 100:
            self._flush()

    def on_error(self, failure):
        self.http_errors += 1
        url = failure.request.meta.get("detail_url", "?")
        self.logger.debug(f"Failed: {url}")

    def _flush(self):
        if not self._batch:
            return
        with self.engine.begin() as conn:
            for bid, rating, people, isbn, l1_name, l2_name, l3_name in self._batch:
                conn.execute(
                    text("""UPDATE books SET
                        rating=:r, rating_people=:p,
                        isbn=COALESCE(:isbn, books.isbn),
                        category_l1_name=COALESCE(:l1, books.category_l1_name),
                        category_l2_name=COALESCE(:l2, books.category_l2_name),
                        category_l3_name=COALESCE(:l3, books.category_l3_name)
                    WHERE id=:id"""),
                    {"r": rating, "p": people, "isbn": isbn, "l1": l1_name, "l2": l2_name, "l3": l3_name, "id": bid},
                )
        self.updated += len(self._batch)
        self._batch = []

    def closed(self, reason):
        self._flush()
        self.logger.info(
            f"Done: {self.updated} updated, {self.http_errors} http errors, "
            f"{self.no_rating} no-rating pages"
        )

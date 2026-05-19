import os
import scrapy
from dotenv import load_dotenv
from dangdang_scrapy.db import get_engine
from dangdang_scrapy.parsers import parse_detail_rating
from sqlalchemy import text

load_dotenv()
USE_PW = os.environ.get("DANGDANG_USE_PLAYWRIGHT", "").lower() in ("1", "true", "yes")


class DangdangDetailSpider(scrapy.Spider):
    name = "dangdang_detail"
    allowed_domains = ["product.dangdang.com", "dangdang.com"]

    custom_settings = {
        "CONCURRENT_REQUESTS": 8,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 8,
        "DOWNLOAD_DELAY": 0.5,
        "RANDOMIZE_DOWNLOAD_DELAY": True,
        "DOWNLOAD_TIMEOUT": 30,
        "RETRY_TIMES": 2,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 4.0,
        "AUTOTHROTTLE_START_DELAY": 0.5,
        "AUTOTHROTTLE_MAX_DELAY": 5.0,
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
        self._total_urls = 0
        self._processed = 0

    def start_requests(self):
        urls = self._fetch_pending()
        self._total_urls = len(urls)
        self.logger.info(f"Pending {self._total_urls} URLs to backfill")
        for bid, detail_url in urls:
            meta = {"id": bid, "detail_url": detail_url}
            if USE_PW:
                from scrapy_playwright.page import PageMethod
                meta["playwright"] = True
                meta["playwright_page_methods"] = [
                    PageMethod("wait_for_selector", "#comm_num_down, span.star", timeout=5000),
                    PageMethod("wait_for_timeout", 500),
                ]
            yield scrapy.Request(url=detail_url, callback=self.parse, meta=meta, errback=self.on_error)

    def _fetch_pending(self):
        sql = """SELECT id, detail_url FROM books
                 WHERE detail_url LIKE '%product.dangdang.com%'
                   AND (rating IS NULL OR rating = 0
                        OR rating_people IS NULL OR rating_people = 0)
                 ORDER BY id"""
        with self.engine.connect() as conn:
            return [(row[0], row[1]) for row in conn.execute(text(sql))]

    def parse(self, response):
        bid = response.meta["id"]
        rating, people = parse_detail_rating(response.text)
        if rating is None and people is None:
            self.no_rating += 1
        self._batch.append((bid, rating, people))
        self._processed += 1
        if len(self._batch) >= 100:
            self._flush()
            pct = self._processed * 100 // self._total_urls if self._total_urls else 0
            self.logger.info(f"Progress: {self._processed}/{self._total_urls} ({pct}%)")

    def on_error(self, failure):
        self.http_errors += 1
        url = failure.request.meta.get("detail_url", "?")
        self.logger.debug(f"Failed: {url}")

    def _flush(self):
        if not self._batch:
            return
        with self.engine.begin() as conn:
            for bid, rating, people in self._batch:
                conn.execute(
                    text("UPDATE books SET rating=:r, rating_people=:p WHERE id=:id"),
                    {"r": rating, "p": people, "id": bid},
                )
        self.updated += len(self._batch)
        self._batch = []

    def closed(self, reason):
        self._flush()
        self.logger.info(
            f"Done: {self.updated} updated, {self.http_errors} http errors, "
            f"{self.no_rating} no-rating pages"
        )

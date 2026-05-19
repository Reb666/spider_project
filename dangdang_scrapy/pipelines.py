import pandas as pd
from sqlalchemy import text
from dangdang_scrapy.db import get_engine, init_db, upsert_books
from dangdang_scrapy.parsers import parse_price, parse_rating_from_style, parse_int


class BookCleaningPipeline:
    def process_item(self, item, spider):
        item["price"] = parse_price(item.get("price"))
        item["original_price"] = parse_price(item.get("original_price"))
        item["rating"] = parse_rating_from_style(item.get("rating")) if isinstance(item.get("rating"), str) else item.get("rating")
        item["sales"] = parse_int(item.get("sales"))
        item["rating_people"] = parse_int(item.get("rating_people"))
        for field in ("name", "author", "publisher"):
            if item.get(field):
                item[field] = item[field].strip()
        return item


class DatabasePipeline:
    BATCH_SIZE = 1000

    def open_spider(self, spider):
        self.items = []
        self.disabled = False
        try:
            self.engine = get_engine()
            init_db()
            self.db_ok = True
            spider.logger.info("Database connected")
        except Exception as e:
            if spider.name == "dangdang":
                spider.logger.warning(f"DB unavailable ({e}), falling back to feed export")
                self.disabled = True
                return
            raise

    def process_item(self, item, spider):
        if self.disabled:
            return item
        self.items.append(dict(item))
        if len(self.items) >= self.BATCH_SIZE:
            self._flush(spider)
        return item

    def close_spider(self, spider):
        if self.disabled or not self.items:
            return
        self._flush(spider)

    def _flush(self, spider):
        if not self.items:
            return
        df = pd.DataFrame(self.items).drop_duplicates(subset=["detail_url"])
        self.items = []
        before = len(df)
        df = df.dropna(subset=["detail_url"])
        # pandas 会把 None 转成 NaN，需要转回 None 才能正确写入 PostgreSQL NULL
        df = df.where(pd.notna(df), None)
        if not df.empty:
            upsert_books(df)
        spider.logger.info(f"Saved {len(df)} books ({before - len(df)} duplicates/empty skipped)")

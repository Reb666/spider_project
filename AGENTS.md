# dangdang_scrapy — AGENTS.md

## You are the crawler developer

Your domain = all files under `dangdang_scrapy/`, `tests/`, `scripts/`, `quality_checks.py`, `Makefile`. You own spiral: user story → spider/parser → pipeline → DB → export → analysis.

## Commands (all via Conda env `dangdang_scrapy`)

| Command | What |
|---------|------|
| `make setup` | Docker PG up + deps + init_db |
| `make crawl` | `scrapy crawl dangdang` (listing, JOBDIR resume) |
| `make detail` | `scrapy crawl dangdang_detail` (rating backfill, JOBDIR resume) |
| `make export` | DB → `data/books.csv` |
| `make analyze` | Matplotlib charts → `analysis/` |
| `make quality` | Data quality report |
| `make verify-fast` | Unit tests + export + analyze smoke (DB required) |
| `make verify-e2e` | verify-fast + runtime assertion (needs data) |
| `make test-full` | All tests (incl integration) on `_test` DB |
| `make reset-db` | docker compose down -v + up + init_db |
| `pytest -m "not integration"` | Unit tests only |
| `make psql` | `docker compose exec postgres psql` |
| `make logs` | `tail -f data/*.log` |

All commands run from project root. `.env` is gitignored — `cp .env.example .env` first.

## Strategy: two spiders, two layouts, dual rendering

**`dangdang` spider** (`spiders/dangdang.py`): crawls category listing pages. Two sub-parsers handle 当当's two layouts:
- **标准** (`ul.bigimg li`) — full info (name, author, publisher, price, rating, review count)
- **促销** (`div.cloth_good_sort li`) — minimal info (name, price only; no author/rating)

Both yield `BookItem` → `BookCleaningPipeline` (200) → `DatabasePipeline` (300, batch upsert 1000).

**`dangdang_detail` spider** (`spiders/dangdang_detail.py`): backfills rating/rating_people from detail pages. Reads pending URLs (`rating IS NULL OR rating = 0`) from DB, updates in 100-row batches via `UPDATE`. Has its own `custom_settings` (faster concurrency, no pipelines). Raises on DB failure (no fallback).

**Dual rendering**: `DANGDANG_USE_PLAYWRIGHT=true` switches from native HTTP to `scrapy-playwright` with `wait_for_selector`. Affects both spiders.

## Key protection mechanisms

| Mechanism | File:Line | What |
|-----------|-----------|------|
| URL normalization | `spiders/dangdang.py:12` | Strips tracking params, rejects `jump.php`, only keeps `product.dangdang.com` |
| Pagination guard | `spiders/dangdang.py:81` | `MAX_EMPTY_PAGES=3` + `MAX_PAGES_PER_CATEGORY=50` stop infinite loops |
| Item filter | `spiders/dangdang.py:95` | Post-parse filter on name/author/publisher/rating/price/people |
| Dedup + skip | `pipelines.py:51` | `_flush()` drops dupes by `detail_url`, rows missing `detail_url`, then `ON CONFLICT DO NOTHING` |
| Graceful DB fallback | `pipelines.py:31` | `dangdang` spider degrades to feed export when PG down; `dangdang_detail` raises |

## Key function locations

- **`_normalize_url()`** → `spiders/dangdang.py:12`
- **`_parse_standard_items()`** → `spiders/dangdang.py:174` (uses CSS `ul.bigimg li`)
- **`_parse_promo_items()`** → `spiders/dangdang.py:194` (uses CSS `div.cloth_good_sort li`)
- **`_follow_next()`** → `spiders/dangdang.py:214` (next page via `li.next a`)
- **`parse_detail_rating()`** → `parsers.py:36` (regex on `width:X%` and `comm_num_down`)
- **`upsert_books()`** → `db.py:51` (`INSERT ... ON CONFLICT (detail_url) DO NOTHING`)
- **`_request_meta()`** → `spiders/dangdang.py:29` (Playwright PageMethod injection)

## Rating scale

0–100 (90 = 4.5 stars). Parsed from CSS `width:X%` on list pages, or regex `width:X%` on detail pages.

## DB details

- PostgreSQL on **port 5433**, container `dangdang-pg`
- `BookItem` fields: name, author, publisher, price, original_price, rating, rating_people, sales, detail_url, category
- `dbo.upsert_books()` converts NaN→None for PostgreSQL NULL safety (pandas quirk)
- `db.get_engine()` is a stateful singleton — call `db.reset_engine()` before changing `DATABASE_URL`

## Testing

- Integration tests marked `@pytest.mark.integration`, skipped unless `TEST_DATABASE_URL` set
- `TEST_DATABASE_URL` **must end with `_test`** — safety check in `test_db_pipeline.py`
- Fixture HTML pages in `tests/fixtures/`, no network needed for unit tests
- `test_spiders.py` uses `_make_response()` helper with local fixture files
- `from dangdang_scrapy.db import reset_engine; reset_engine()` before integration tests
- New parsers → `tests/test_parsers.py` (normal/null/edge cases)

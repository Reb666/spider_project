# dangdang_scrapy — AGENTS.md

## Commands (all via Conda env `dangdang_scrapy`)

| Command | What |
|---------|------|
| `make setup` | Docker PG up + deps + init_db |
| `make crawl` | `scrapy crawl dangdang` (listing) |
| `make detail` | `scrapy crawl dangdang_detail` (rating backfill) |
| `make export` | DB → `data/books.csv` |
| `make analyze` | Matplotlib charts → `analysis/` |
| `make quality` | Data quality report |
| `make verify-fast` | Unit tests + export + analyze smoke (DB required) |
| `make verify-e2e` | verify-fast + runtime assertion (needs data) |
| `make test-full` | All tests (incl integration) on `_test` DB |
| `make reset-db` | docker compose down -v + up + init_db |
| `make psql` | `docker compose exec postgres psql` |
| `pytest -m "not integration"` | Unit tests only |

## Architecture

- **Two spiders**: `dangdang` (list pages → `BookItem`), `dangdang_detail` (detail pages → UPDATE rating/rating_people)
- **Dual mode**: `DANGDANG_USE_PLAYWRIGHT=true` switches to Playwright rendering (default: native HTTP)
- **Pipelines**: `BookCleaningPipeline` (200) → `DatabasePipeline` (300, batch upsert 1000)
- **DB fallback**: `dangdang` spider degrades gracefully if PG unreachable; `dangdang_detail` raises
- **Dedup**: `ON CONFLICT (detail_url) DO NOTHING` in `db.upsert_books()`
- **Rating**: 0–100 scale (90 = 4.5 stars)
- **Port**: PostgreSQL on **5433** (not 5432)
- **`backfill_ratings.py`**: deprecated, use `scrapy crawl dangdang_detail`

## Testing

- Integration tests marked `@pytest.mark.integration`, skipped unless `TEST_DATABASE_URL` set
- `TEST_DATABASE_URL` **must end with `_test`** — safety check in `test_db_pipeline.py`
- Before integration tests: call `db.reset_engine()` so cached singleton picks up test URL
- Fixture HTML pages in `tests/fixtures/`, no network needed for unit tests
- `test_spiders.py` uses `_make_response()` helper with local fixture files

## Conventions

- New parsers go in `parsers.py`, new tests in `tests/test_parsers.py` (normal/null/edge cases)
- `url_normalize` in `spiders/dangdang.py` as `_normalize_url()` — strips tracking params, rejects `jump.php`
- `BookItem` fields: name, author, publisher, price, original_price, rating, rating_people, sales, detail_url, category
- Pipeline `_flush()` drops duplicates by `detail_url` and drops rows missing `detail_url` before upsert

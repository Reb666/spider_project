import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

_engine = None
_engine_url = None

_SCHEMA_V1_COLS = """id SERIAL PRIMARY KEY,
    name VARCHAR(500), author VARCHAR(500), publisher VARCHAR(300),
    price DOUBLE PRECISION, original_price DOUBLE PRECISION,
    rating DOUBLE PRECISION, rating_people BIGINT, sales BIGINT,
    detail_url VARCHAR(1000), category VARCHAR(200),
    isbn VARCHAR(20),
    category_l1_id VARCHAR(10), category_l2_id VARCHAR(10),
    category_l1_name VARCHAR(200), category_l2_name VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"""


def get_engine(database_url: str = None):
    global _engine, _engine_url
    requested = database_url or os.environ.get("DATABASE_URL")
    if not requested:
        raise RuntimeError("DATABASE_URL 未设置。请复制 .env.example 为 .env 并填入配置")
    if _engine is not None and requested != _engine_url:
        raise RuntimeError(
            f"engine 已用 {_engine_url} 初始化，不能用 {requested}"
        )
    if _engine is None:
        _engine_url = requested
        _engine = create_engine(requested, connect_args={"connect_timeout": 5})
    return _engine


def reset_engine():
    global _engine, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _engine_url = None


def init_db():
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS books (
                {_SCHEMA_V1_COLS}
            )
        """))
        _migrate_v1(conn)
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_books_url ON books (detail_url)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_books_isbn ON books (isbn) WHERE isbn IS NOT NULL AND isbn != ''"))


def _migrate_v1(conn):
    """Add columns introduced in later versions."""
    existing = {row[0] for row in conn.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name='books'"
    ))}
    new_cols = {
        "isbn": "VARCHAR(20)",
        "category_l1_id": "VARCHAR(10)",
        "category_l2_id": "VARCHAR(10)",
        "category_l1_name": "VARCHAR(200)",
        "category_l2_name": "VARCHAR(200)",
    }
    for col, dtype in new_cols.items():
        if col not in existing:
            conn.execute(text(f"ALTER TABLE books ADD COLUMN {col} {dtype}"))


def upsert_books(df: pd.DataFrame, batch_size: int = 100):
    engine = get_engine()
    stmt = text("""
        INSERT INTO books (name, author, publisher, price, original_price,
                           rating, rating_people, sales, detail_url, category,
                           isbn, category_l1_id, category_l2_id, category_l1_name, category_l2_name)
        VALUES (:name, :author, :publisher, :price, :original_price,
                :rating, :rating_people, :sales, :detail_url, :category,
                :isbn, :category_l1_id, :category_l2_id, :category_l1_name, :category_l2_name)
        ON CONFLICT (detail_url) DO UPDATE SET
            name = EXCLUDED.name,
            author = EXCLUDED.author,
            publisher = EXCLUDED.publisher,
            price = EXCLUDED.price,
            original_price = EXCLUDED.original_price,
            rating = EXCLUDED.rating,
            rating_people = EXCLUDED.rating_people,
            sales = EXCLUDED.sales,
            category = EXCLUDED.category,
            isbn = COALESCE(EXCLUDED.isbn, books.isbn),
            category_l1_id = COALESCE(EXCLUDED.category_l1_id, books.category_l1_id),
            category_l2_id = COALESCE(EXCLUDED.category_l2_id, books.category_l2_id),
            category_l1_name = COALESCE(EXCLUDED.category_l1_name, books.category_l1_name),
            category_l2_name = COALESCE(EXCLUDED.category_l2_name, books.category_l2_name)
            WHERE books.detail_url IS NOT NULL
    """)
    df = df.copy()
    for col in ("rating_people", "sales"):
        if col in df.columns:
            df[col] = df[col].where(pd.notna(df[col]), None)
    for col in ("isbn", "category_l1_id", "category_l2_id", "category_l1_name", "category_l2_name"):
        if col not in df.columns:
            df[col] = None
    with engine.begin() as conn:
        for start in range(0, len(df), batch_size):
            batch = df.iloc[start:start + batch_size]
            rows = batch.to_dict(orient="records")
            conn.execute(stmt, rows)
    return len(df)

import os
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

_engine = None
_engine_url = None


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
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS books (
                id SERIAL PRIMARY KEY,
                name VARCHAR(500), author VARCHAR(500), publisher VARCHAR(300),
                price DOUBLE PRECISION, original_price DOUBLE PRECISION,
                rating DOUBLE PRECISION, rating_people BIGINT, sales BIGINT,
                detail_url VARCHAR(1000), category VARCHAR(200),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_books_url ON books (detail_url)"))


def upsert_books(df: pd.DataFrame, batch_size: int = 100):
    engine = get_engine()
    stmt = text("""
        INSERT INTO books (name, author, publisher, price, original_price,
                           rating, rating_people, sales, detail_url, category)
        VALUES (:name, :author, :publisher, :price, :original_price,
                :rating, :rating_people, :sales, :detail_url, :category)
        ON CONFLICT (detail_url) DO NOTHING
    """)
    df = df.copy()
    for col in ("rating_people", "sales"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
    with engine.begin() as conn:
        for start in range(0, len(df), batch_size):
            batch = df.iloc[start:start + batch_size]
            rows = batch.to_dict(orient="records")
            conn.execute(stmt, rows)
    return len(df)

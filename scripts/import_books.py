"""导入 data/books.csv 到 PostgreSQL（首次 setup 使用）。"""
import os, sys, pandas as pd
from dangdang_scrapy.db import get_engine, init_db, upsert_books

path = os.path.join(os.path.dirname(__file__), "..", "data", "books.csv")
if not os.path.exists(path):
    print(f"未找到 {path}，跳过导入")
    sys.exit(0)

df = pd.read_csv(path)
before = len(df)

# 过滤掉杂志/跳转链接等脏数据
if "detail_url" in df.columns:
    df = df[~df["detail_url"].str.contains("jump.php", na=False)]
    df = df[~df["name"].str.contains("杂志|期刊", na=False)]

print(f"过滤前 {before} 条，过滤后 {len(df)} 条")

init_db()
upsert_books(df)
print(f"导入 {len(df)} 条完成")

"""当当爬虫 Web 控制面板 — Flask 应用"""
import os, sys, subprocess, json, threading, math, shutil
from datetime import datetime
from pathlib import Path

# 确保项目根目录在 sys.path 中，方便导入 dangdang_scrapy
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from flask import Flask, render_template, request, jsonify, url_for
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from dangdang_scrapy.db import get_engine

app = Flask(__name__)

# ---- 爬虫进程状态 ----
_crawl_process = None
_crawl_started_at = None
_crawl_spider_name = None
_crawl_db_count_before = 0   # 爬前数据库条数（列表爬虫用）
_crawl_target = 0            # 目标条数
_crawl_missing_before = 0    # 爬前缺失数（详情补抓用）
_lock = threading.Lock()


def _engine():
    return get_engine()


def _clean_nan(obj):
    """递归将所有 NaN 替换为 None（jsonify 会把 None 输出为合法的 null）"""
    if isinstance(obj, float) and math.isnan(obj):
        return None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nan(v) for v in obj]
    return obj


# ================================================================
# 页面
# ================================================================

@app.route("/")
def index():
    return render_template("index.html")


# ================================================================
# API — 爬虫控制
# ================================================================

@app.route("/api/crawl/start", methods=["POST"])
def crawl_start():
    global _crawl_process, _crawl_started_at, _crawl_spider_name
    global _crawl_db_count_before, _crawl_target, _crawl_missing_before
    with _lock:
        if _crawl_process and _crawl_process.poll() is None:
            return jsonify({"ok": False, "message": "已有爬虫正在运行"}), 409

        data = request.get_json(silent=True) or {}
        item_count = data.get("item_count", 0) or 0

        cmd = [
            sys.executable, "-m", "scrapy", "crawl", "dangdang",
        ]
        if item_count > 0:
            cmd += ["-a", f"max_items={item_count}"]
            # Scrapy 内置安全网：双重保险防止爬取数量超标
            cmd += ["-s", f"CLOSESPIDER_ITEMCOUNT={item_count}"]

        # 传递筛选参数给 spider
        for key in ("name_filter", "author_filter", "publisher_filter",
                     "rating_min", "rating_max", "price_min", "price_max", "people_min"):
            val = data.get(key)
            if val is not None and str(val).strip():
                cmd += ["-a", f"{key}={str(val).strip()}"]

        # 记录爬前状态（用于进度条）
        try:
            engine = _engine()
            with engine.connect() as conn:
                _crawl_db_count_before = conn.execute(
                    text("SELECT COUNT(*) FROM books")
                ).scalar()
        except Exception:
            _crawl_db_count_before = 0
        _crawl_target = item_count
        _crawl_missing_before = 0

        _crawl_process = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _crawl_started_at = datetime.utcnow()
        _crawl_spider_name = "dangdang"

    return jsonify({
        "ok": True,
        "message": "列表爬虫已启动",
        "item_count": item_count or None,
        "db_count_before": _crawl_db_count_before,
    })


@app.route("/api/crawl/detail", methods=["POST"])
def crawl_detail():
    global _crawl_process, _crawl_started_at, _crawl_spider_name
    global _crawl_db_count_before, _crawl_target, _crawl_missing_before
    with _lock:
        if _crawl_process and _crawl_process.poll() is None:
            return jsonify({"ok": False, "message": "已有爬虫正在运行"}), 409

        # 记录爬前缺失数（用于进度条）
        try:
            engine = _engine()
            with engine.connect() as conn:
                _crawl_missing_before = conn.execute(text(
                    "SELECT COUNT(*) FROM books WHERE (rating IS NULL OR rating = 0"
                    " OR rating_people IS NULL OR rating_people = 0)"
                    " AND detail_url LIKE '%product.dangdang.com%'"
                )).scalar()
        except Exception:
            _crawl_missing_before = 0
        _crawl_db_count_before = 0
        _crawl_target = 0

        # 清理旧 job 目录，确保每次爬取从零开始
        jobdir = os.path.join(PROJECT_ROOT, "jobs", "detail")
        if os.path.isdir(jobdir):
            shutil.rmtree(jobdir)

        _crawl_process = subprocess.Popen(
            [sys.executable, "-m", "scrapy", "crawl", "dangdang_detail"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _crawl_started_at = datetime.utcnow()
        _crawl_spider_name = "dangdang_detail"

    return jsonify({"ok": True, "message": "详情补抓已启动"})


@app.route("/api/crawl/status")
def crawl_status():
    global _crawl_process, _crawl_started_at, _crawl_spider_name
    global _crawl_db_count_before, _crawl_target, _crawl_missing_before
    with _lock:
        if _crawl_process is None:
            return jsonify({"running": False, "started_at": None, "spider": None})

        retcode = _crawl_process.poll()

        # 计算进度
        progress = None
        try:
            engine = _engine()
            with engine.connect() as conn:
                if _crawl_spider_name == "dangdang":
                    current = conn.execute(text("SELECT COUNT(*) FROM books")).scalar()
                    done = max(0, current - _crawl_db_count_before)
                    if _crawl_target > 0:
                        progress = min(100, round(done / _crawl_target * 100))
                    else:
                        progress = done  # 不限条数时显示已抓条数
                else:
                    # dangdang_detail: 统计剩余缺失数
                    remaining = conn.execute(text(
                        "SELECT COUNT(*) FROM books WHERE (rating IS NULL OR rating = 0"
                        " OR rating_people IS NULL OR rating_people = 0)"
                        " AND detail_url LIKE '%product.dangdang.com%'"
                    )).scalar()
                    if _crawl_missing_before > 0:
                        done = _crawl_missing_before - remaining
                        progress = min(100, round(done / _crawl_missing_before * 100))
                    else:
                        progress = None
        except Exception:
            progress = None

        if retcode is None:
            elapsed = str(datetime.utcnow() - _crawl_started_at).split(".")[0]
            return jsonify({
                "running": True,
                "started_at": _crawl_started_at.isoformat(),
                "spider": _crawl_spider_name,
                "elapsed": elapsed,
                "progress": progress,
            })
        else:
            elapsed = str(datetime.utcnow() - _crawl_started_at).split(".")[0] if _crawl_started_at else ""
            result = {
                "running": False,
                "started_at": _crawl_started_at.isoformat() if _crawl_started_at else None,
                "spider": _crawl_spider_name,
                "elapsed": elapsed,
                "exit_code": retcode,
                "progress": 100,
            }
            _crawl_process = None
            _crawl_started_at = None
            _crawl_spider_name = None
            _crawl_db_count_before = 0
            _crawl_target = 0
            _crawl_missing_before = 0
            return jsonify(result)


@app.route("/api/crawl/stop", methods=["POST"])
def crawl_stop():
    global _crawl_process, _crawl_started_at, _crawl_spider_name
    global _crawl_db_count_before, _crawl_target, _crawl_missing_before
    with _lock:
        if _crawl_process and _crawl_process.poll() is None:
            _crawl_process.terminate()
            try:
                _crawl_process.wait(timeout=5)
            except Exception:
                _crawl_process.kill()
            _crawl_process = None
            _crawl_started_at = None
            _crawl_spider_name = None
            _crawl_db_count_before = 0
            _crawl_target = 0
            _crawl_missing_before = 0
            return jsonify({"ok": True, "message": "爬虫已终止"})
        else:
            _crawl_process = None
            return jsonify({"ok": True, "message": "没有正在运行的爬虫"})


@app.route("/api/books/clear", methods=["POST"])
def clear_books():
    """清空 books 表所有数据"""
    try:
        engine = _engine()
        with engine.begin() as conn:
            result = conn.execute(text("DELETE FROM books"))
            deleted = result.rowcount
        return jsonify({"ok": True, "message": f"已删除 {deleted} 条记录"})
    except Exception as e:
        return jsonify({"ok": False, "message": f"清空失败: {e}"}), 500


# ================================================================
# API — 书籍查询
# ================================================================

# 安全的排序列白名单
ALLOWED_SORT = {
    "name", "author", "publisher", "price", "original_price",
    "rating", "rating_people", "category", "id", "created_at",
}


@app.route("/api/books")
def api_books():
    """查询书籍（筛选 + 排序 + 分页）"""
    try:
        engine = _engine()
    except Exception as e:
        return jsonify({"ok": False, "message": f"数据库连接失败: {e}"}), 500

    # 筛选参数
    name = request.args.get("name", "").strip()
    author = request.args.get("author", "").strip()
    publisher = request.args.get("publisher", "").strip()
    rating_min = request.args.get("rating_min", type=float)
    rating_max = request.args.get("rating_max", type=float)
    people_min = request.args.get("people_min", type=int)
    price_min = request.args.get("price_min", type=float)
    price_max = request.args.get("price_max", type=float)
    sort_by = request.args.get("sort_by", "id")
    sort_order = request.args.get("sort_order", "desc")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)

    # 安全校验
    if sort_by not in ALLOWED_SORT:
        sort_by = "id"
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"
    page = max(1, page)
    per_page = min(max(1, per_page), 100)

    where = []
    params = {}
    if name:
        where.append("name ILIKE :name")
        params["name"] = f"%{name}%"
    if author:
        where.append("author ILIKE :author")
        params["author"] = f"%{author}%"
    if publisher:
        where.append("publisher ILIKE :publisher")
        params["publisher"] = f"%{publisher}%"
    if rating_min is not None:
        where.append("rating >= :rating_min")
        params["rating_min"] = rating_min
    if rating_max is not None:
        where.append("rating <= :rating_max")
        params["rating_max"] = rating_max
    if people_min is not None:
        where.append("rating_people >= :people_min")
        params["people_min"] = people_min
    if price_min is not None:
        where.append("price >= :price_min")
        params["price_min"] = price_min
    if price_max is not None:
        where.append("price <= :price_max")
        params["price_max"] = price_max

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    # 总数 + 分页
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM books {where_clause}"), params).scalar()
        rows = conn.execute(
            text(
                f"SELECT id, name, author, publisher, price, original_price, "
                f"rating, rating_people, detail_url, category, created_at "
                f"FROM books {where_clause} ORDER BY {sort_by} {sort_order} "
                f"LIMIT :limit OFFSET :offset"
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        )
        columns = rows.keys()
        books = [dict(zip(columns, row)) for row in rows]

    # 处理日期格式
    for b in books:
        if b.get("created_at"):
            b["created_at"] = b["created_at"].isoformat()

    return jsonify(_clean_nan({
        "ok": True,
        "books": books,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }))


# ================================================================
# API — 统计数据（图表用）
# ================================================================

@app.route("/api/stats")
def api_stats():
    """返回 ECharts 需要的聚合数据"""
    try:
        engine = _engine()
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM books")).scalar()

        if total == 0:
            return jsonify({"ok": True, "total": 0})

        # 评分分布: 10 档（price=price 排除 NaN，NaN 永远不等于自身）
        rating_rows = conn.execute(text("""
            SELECT width_bucket(rating, 0, 100, 10) AS bucket, COUNT(*)::int
            FROM books WHERE rating IS NOT NULL AND rating > 0 AND rating = rating
            GROUP BY bucket ORDER BY bucket
        """)).all()
        rating_buckets = [
            {"label": f"{i*10}-{(i+1)*10}", "count": 0} for i in range(10)
        ]
        for b, c in rating_rows:
            if 1 <= b <= 10:
                rating_buckets[b - 1]["count"] = c

        # 价格分布: 20 档
        price_rows = conn.execute(text("""
            SELECT width_bucket(price, 0, 200, 20) AS bucket, COUNT(*)::int
            FROM books WHERE price IS NOT NULL AND price > 0 AND price = price
            GROUP BY bucket ORDER BY bucket
        """)).all()
        price_buckets = [
            {"label": f"{i*10}-{(i+1)*10}", "count": 0} for i in range(20)
        ]
        for b, c in price_rows:
            if 1 <= b <= 20:
                price_buckets[b - 1]["count"] = c

        # 出版社 Top10
        pub_rows = conn.execute(text("""
            SELECT publisher, COUNT(*)::int AS cnt
            FROM books WHERE publisher IS NOT NULL AND publisher != ''
            GROUP BY publisher ORDER BY cnt DESC LIMIT 10
        """)).all()
        publishers = [{"name": r[0], "count": r[1]} for r in pub_rows]

        # 评分 vs 价散点（最多取 3000 条，避免浏览器渲染卡死）
        scatter_rows = conn.execute(text("""
            SELECT price, rating FROM books
            WHERE price IS NOT NULL AND rating IS NOT NULL AND rating > 0
              AND price = price AND rating = rating
            ORDER BY RANDOM() LIMIT 3000
        """)).all()
        scatter = [{"price": float(r[0]), "rating": float(r[1])} for r in scatter_rows if r[0] and r[1]]

    return jsonify(_clean_nan({
        "ok": True,
        "total": total,
        "rating_distribution": rating_buckets,
        "price_distribution": price_buckets,
        "top_publishers": publishers,
        "scatter": scatter,
    }))


# ================================================================
# 启动
# ================================================================

if __name__ == "__main__":
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Open: http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)

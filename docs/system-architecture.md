# 当当网图书爬虫 — 系统结构分析

## 1. 总体架构

```
┌──────────────────────────────────────────────────────┐
│                    用户 / 开发者                        │
│   make crawl  make detail  make export  make analyze  │
└──────────┬──────────┬──────────┬──────────────────────┘
           │          │          │
┌──────────▼──────────▼──────────▼──────────────────────┐
│                    Makefile / CLI                        │
│   Conda env: dangdang_scrapy                            │
│   DATABASE_URL 环境变量驱动                              │
└───────┬──────────────┬──────────────────┬──────────────┘
        │              │                  │
┌───────▼──────┐ ┌─────▼──────┐  ┌───────▼────────┐
│  dangdang    │ │dangdang_   │  │ scripts/        │
│  spider      │ │detail      │  │ export_books.py │
│  (列表页)    │ │spider      │  │ import_books.py │
│              │ │(详情页补分) │  │ assert_runtime. │
│  Playwright ◄┼►│Playwright  │  │ py              │
│  (可选)      │ │(可选)      │  └────────┬────────┘
└───────┬──────┘ └──────┬─────┘           │
        │               │                 │
        ▼               ▼                 ▼
┌──────────────────────────────────────────────────────┐
│                 pipelines.py                           │
│  BookCleaningPipeline (200) → DatabasePipeline (300)  │
│    ↓ 数值清洗、去空白        ↓ batch upsert 1000      │
│    ↓ 字符串归一化            ↓ drop_duplicates        │
│    ↓                         ↓ PG 不可用→FEED fallback │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│                  dangdang_scrapy/db.py                 │
│   get_engine() (单例) → init_db() → upsert_books()    │
│   ON CONFLICT (detail_url) DO NOTHING                 │
│   DataFrame NaN → None 转换                            │
└────────────────────────┬─────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│         PostgreSQL 16 (docker, port 5433)              │
│         ┌──────────────────────────┐                  │
│         │  books 表                 │                  │
│         │  id, name, author, ...    │                  │
│         │  detail_url UNIQUE INDEX  │                  │
│         │  created_at DEFAULT NOW   │                  │
│         └──────────────────────────┘                  │
└────────────────────────┬─────────────────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
     ┌────────────┐ ┌────────┐ ┌──────────┐
     │ data/      │ │analysis│ │ web/app  │
     │ books.csv  │ │ .png   │ │ .py      │
     └────────────┘ └────────┘ └──────────┘
             数据分析    可视化    Web 浏览
```

## 2. 组件详解

### 2.1 列表爬虫（dangdang spider）

**文件**: `spiders/dangdang.py`

**策略**: 两遍解析（Two-Pass Parsing）

```
start_urls (22 个分类入口)
    │
    ├── 标准布局 → parse_standard()
    │     └── _parse_standard_items()  ← CSS ul.bigimg li
    │     └── _follow_next()           ← li.next a
    │
    └── 促销布局 → parse_promotional()
          └── _parse_promo_items()     ← CSS div.cloth_good_sort li
          └── _follow_next()           ← li.next a
```

**关键设计**:
- `_normalize_url()`（`spiders/dangdang.py:12`）: 统一入口清洗 URL，拒绝跳转链，仅保留 `product.dangdang.com`
- `_request_meta()`（`spiders/dangdang.py:29`）: Playwright 模式下注入 `PageMethod("wait_for_selector", ...)`
- `_should_follow_next()`（`spiders/dangdang.py:81`）: 双重守卫——有过滤条件时连续 3 页无结果即停，最多 50 页/分类
- `_passes_filter()`（`spiders/dangdang.py:95`）: 在 spider 层过滤而非 DB 层，节省带宽和存储

### 2.2 详情补分爬虫（dangdang_detail spider）

**文件**: `spiders/dangdang_detail.py`

**策略**: 从 DB 读待补 URL → 并发请求 → 批量 UPDATE

```
_db 读取 pending URLs_
    │ (WHERE rating IS NULL OR rating = 0)
    ▼
_scrapy.Request → parse()_
    │ regex: width:X% + comm_num_down
    ▼
_batch.append() → 满 100 条 _flush()_
    ▼
_UPDATE books SET rating=:r, rating_people=:p WHERE id=:id_
```

**独立配置**（`custom_settings`）:
- 更高并发（8 vs 6）、更低延迟（0.5s vs 2s）、4.0 AutoThrottle 并发目标
- 空管道（`ITEM_PIPELINES = {}`），直接走 spider 内 `_flush`
- 无 DB 降级（DB 失败直接 raise）

### 2.3 解析器（parsers.py）

**文件**: `parsers.py`

纯函数式设计，零副作用，便于单元测试。

| 函数 | 输入 | 输出 | 实现 |
|------|------|------|------|
| `parse_price()` | `"¥35.70"` | `35.7` | 正则 `\d+\.?\d*` |
| `parse_int()` | `"35,672条评论"` | `35672` | 去逗号后正则 `\d+` |
| `parse_rating_from_style()` | `"width:90.4%"` | `90.4` | 正则 `width:\s*([\d.]+)%` |
| `parse_detail_rating()` | HTML 全文 | `(96.8, 1525)` | 两个正则匹配评分 + 评论数 |

### 2.4 管道（pipelines.py）

```
BookItem
    │
    ▼
BookCleaningPipeline (优先级 200)
    │ parse_price() 清洗 price/original_price
    │ parse_rating_from_style() 清洗 rating（从字符串到 float）
    │ parse_int() 清洗 rating_people/sales
    │ strip() 清洗 name/author/publisher
    │
    ▼
DatabasePipeline (优先级 300)
    │ open_spider()  → init_db()，PG 失败时 dangdang 降级
    │ process_item() → 攒满 1000 条执行 _flush()
    │ close_spider() → 刷剩余批次
    │
    ▼
upsert_books()
    │ drop_duplicates(subset=['detail_url'])
    │ dropna(subset=['detail_url'])
    │ DataFrame.where(pd.notna(df), None)       ← NaN→None
    │ INSERT ... ON CONFLICT (detail_url) DO NOTHING
```

### 2.5 数据库层（db.py）

**文件**: `db.py`

- `get_engine()` 是状态单例——首次调用后锁定 URL，切换需 `reset_engine()`
- `init_db()` 创建 `books` 表 + `idx_books_url` 唯一索引
- `upsert_books(df, batch_size)` 按批次执行参数化 INSERT，自动转 NaN→None
- 使用 `sqlalchemy` + `psycopg2` 驱动，连接超时 5s

### 2.6 中间件（middlewares.py）

**文件**: `middlewares.py`

`RandomUserAgentMiddleware`（优先级 400）: 从 7 个现代浏览器 UA 中随机选取，覆盖 Chrome/Firefox/Safari/Edge。

## 3. 数据流

```
当当分类页 ──HTTP/Playwright──► dangdang spider
    │                                │
    │  CSS 解析                      │ BookItem
    ▼                                ▼
_parse_standard / _parse_promo ──►  _passes_filter
    │                                │
    │                                ▼
    │                         BookCleaningPipeline
    │                                │
    │                                ▼
    │                         DatabasePipeline._flush()
    │                                │
    │           ┌────────────────────┤
    │           ▼                    ▼
    │     PostgreSQL books      FEED export (PG down)
    │           │
    │           ▼
    │     dangdang_detail spider
    │           │
    │           ▼
    │     UPDATE rating/rating_people
    │
    ▼
scripts/export_books.py ──► data/books.csv ──► analysis/visualize.py
```

## 4. 部署架构

```
┌─────────────────────────────────────────┐
│             宿主机 (Linux)                │
│                                          │
│  Conda env: dangdang_scrapy              │
│    ├── Scrapy (两种 spider)               │
│    ├── Playwright (可选渲染)              │
│    └── pandas / sqlalchemy / matplotlib  │
│                                          │
│  Docker: postgres:16-alpine              │
│    └── container: dangdang-pg            │
│        └── port: 5433 → 5432             │
│            └── volume: pgdata            │
│                                          │
│  数据目录:                                │
│    data/         ← CSV 导出 + 日志        │
│    analysis/     ← Matplotlib 输出图      │
│    jobs/         ← Scrapy JOBDIR 断点     │
└─────────────────────────────────────────┘
```

## 5. 测试架构

```
┌──────────────────────────────────────────────────┐
│                   tests/                           │
│                                                    │
│  ┌──────────────┐  ┌────────────┐  ┌────────────┐ │
│  │ 单元测试      │  │ 集成测试    │  │ 端到端检查  │ │
│  │ -m "not      │  │ -m          │  │ make       │ │
│  │ integration" │  │ integration │  │ verify-e2e │ │
│  │              │  │            │  │            │ │
│  │ test_parsers │  │ test_db_   │  │ assert_    │ │
│  │ .py          │  │ pipeline   │  │ runtime_   │ │
│  │ test_spiders │  │ .py        │  │ state.py   │ │
│  │ .py          │  │ test_      │  │            │ │
│  │ test_url_    │  │ quality_   │  │            │ │
│  │ normalize.py │  │ checks.py  │  │            │ │
│  └──────────────┘  └────────────┘  └────────────┘ │
│        │                 │                │        │
│        │ fixtures/      │ TEST_DATABASE_  │ DB     │
│        │ .html (无网络)  │ URL → _test     │ 有数据  │
│        ▼                 ▼                ▼        │
│    快速 (s)          中等 (min)         慢 (min)   │
└──────────────────────────────────────────────────┘
```

## 6. 关键设计决策

| 决策 | 理由 | 替代方案 |
|------|------|----------|
| 两轮爬取（列表+详情） | 促销布局列表页无评分字段；标准布局评分是 CSS 百分比而非数值，详情页更精确 | 单轮全量爬详情页（带宽浪费 10x） |
| `ON CONFLICT DO NOTHING` 去重 | 天然幂等，支持断点续爬 | `SELECT before INSERT`（非原子，多一次查询） |
| Scrapy pipeline 批量写入 | 减少 DB 连接开销 1000x | 逐条 INSERT（慢，连接压力大） |
| 双渲染模式（HTTP/Playwright） | 按需启用，避免无谓的浏览器开销 | 全量 Playwright（慢 10x，内存高） |
| PG 降级 vs raise | 列表爬取可接受不完整数据；详情补分依赖 DB 状态 | 统一降级（详情补分可能无声丢失数据） |
| 纯函数解析器 | 无状态、可测试、可组合 | 类方法（耦合 spider，难单测） |
| NaN→None 转换 | pandas 默认用 NaN 表示空值，PostgreSQL 需 NULL | 逐列判断（重复代码多） |

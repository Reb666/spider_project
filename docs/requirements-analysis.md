# 当当网图书爬虫 — 需求分析

## 1. 项目背景与目标

当当网（dangdang.com）是国内头部图书电商平台，拥有海量图书的商品信息（书名、作者、出版社、价格、评分等）。本项目旨在系统性地抓取当当网分类列表页的图书数据，并通过详情页补全评分信息，最终形成结构化的图书数据集，支撑后续的数据分析和可视化。

## 2. 用户角色

| 角色 | 职责 |
|------|------|
| **爬虫开发者** | 维护爬虫代码、管道、数据库、测试；保障数据采集的稳定性和质量 |
| **数据分析师** | 消费导出后的 CSV，运行分析脚本生成可视化报表 |
| **运维人员** | 管理 Docker PostgreSQL 实例、环境变量、爬虫调度 |

## 3. 功能需求

### F1 分类列表抓取
- 从当当分类入口页（`category.dangdang.com`）开始遍历
- 支持 当当**两种列表页布局**：
  - **标准布局** (`ul.bigimg li`)：提取书名、作者、出版社、现价、原价、评分（CSS width 百分比）、评论人数
  - **促销布局** (`div.cloth_good_sort li`)：仅提取书名、现价（无作者/出版社/评分）
- 支持翻页，上限 50 页/分类，连续空页 3 次后停止
- 支持爬取时过滤（名称、作者、出版社、评分区间、价格区间、评论人数下限）

### F2 详情页评分补抓
- 从已入库数据中筛选出 `rating IS NULL OR rating = 0` 的记录
- 请求对应的详情页（`product.dangdang.com`），解析评分（`width:X%`）和评论人数（`comm_num_down`）
- 批量回写数据库（100 行一批）

### F3 数据导出
- 将 PostgreSQL `books` 表全量导出为 `data/books.csv`（UTF-8 BOM 编码，兼容 Excel）

### F4 数据可视化
- 基于 CSV 生成价格分布、评分-价格散点、销量分布、出版社 Top-N 等 Matplotlib 图表
- 输出到 `analysis/` 目录

### F5 数据质量报告
- 统计数据库中的数据量、唯一商品数、脏链接率、评分/价格/书名补全率、出版社数、均值等
- 给出定性评价

### F6 Web 浏览（辅助）
- 简单的 Flask Web 应用，支持在浏览器中浏览和过滤已采集的数据

## 4. 非功能需求

### N1 反封锁
- 随机 User-Agent 轮换
- 限流配置：6 并发/域、2s 下载延迟、AutoThrottle 自适应
- 重试机制：3 次重试，覆盖 502/504/500/403/429
- 支持 Playwright 渲染模式以绕过 JS 反爬

### N2 数据质量
- URL 规范化：剔除 `jump.php` 追踪链、只保留 `product.dangdang.com`
- 管道清洗：数值字段统一解析、字符串字段去空白
- 入库去重：`INSERT ... ON CONFLICT (detail_url) DO NOTHING`，辅以 DataFrame 级重复丢弃

### N3 可靠性
- **优雅降级**：列表蜘蛛在 PostgreSQL 不可用时退化为 FEED 导出，不中断爬取
- **详情蜘蛛**：DB 不可用时直接抛出异常，不静默丢失数据
- **可恢复爬取**：通过 Scrapy JOBDIR 支持中断恢复

### N4 隔离性
- 集成测试需 `TEST_DATABASE_URL` 以 `_test` 结尾，防止误操作生产库
- `db.get_engine()` 为单例，切换数据库需调用 `reset_engine()`

### N5 可复现性
- Docker Compose 提供 PostgreSQL 16 容器
- `.env.example` 提供配置模板，`.env` 被 gitignore
- Makefile 封装全部常用操作（setup/crawl/detail/export/analyze/verify）

## 5. 约束

| 约束 | 说明 |
|------|------|
| 页面布局双轨制 | 当当历史原因并存两套列表渲染，必须分别实现解析器 |
| 评分非数值 | 列表页评分以 CSS `width:X%` 呈现，需解析百分比而非直接取数 |
| JS 动态内容 | 部分分类页需 JS 加载商品，需要 Playwright 渲染降级方案 |
| PostgreSQL 端口 | 使用 5433 而非默认 5432，避免与本地 PG 冲突 |
| 环境 | 开发/运行环境为 Conda `dangdang_scrapy`，依赖 playwright chromium |

## 6. 数据字典

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| id | SERIAL PK | 自增 | 主键 |
| name | VARCHAR(500) | 列表页 | 书名 |
| author | VARCHAR(500) | 列表页(标准) | 作者 |
| publisher | VARCHAR(300) | 列表页(标准) | 出版社 |
| price | DOUBLE | 列表页 | 现价 |
| original_price | DOUBLE | 列表页(标准) | 原价 |
| rating | DOUBLE | 列表页/详情页 | 评分 0-100 |
| rating_people | BIGINT | 列表页/详情页 | 评论人数 |
| sales | BIGINT | 未使用 | 销量 |
| detail_url | VARCHAR(1000) UNIQUE | 列表页 | 商品详情链接 |
| category | VARCHAR(200) | meta 传入 | 分类标识 |

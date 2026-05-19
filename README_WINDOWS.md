# dangdang_scrapy — 当当图书爬虫项目（Windows）

> **Linux / macOS 用户请参阅 [README_LINUX.md](README_LINUX.md)**

基于 Scrapy + PostgreSQL 的当当网图书数据采集与分析系统。支持**原生 HTTP**（默认）和 **Playwright**（可选）双模式渲染引擎。

## 目录结构

```
dangdang_scrapy/
├── docker-compose.yml        # PostgreSQL 容器
├── Makefile                   # 一键命令入口（仅 Linux/macOS）
├── requirements.txt           # Python 依赖
├── .env.example              # 环境变量模板
├── README_LINUX.md           # Linux/macOS 教程
├── README_WINDOWS.md         # 本文件 — Windows 教程
├── data/                     # CSV 导出产物
├── scripts/
│   ├── init_db.sql           # 建表 DDL（容器首次启动自动执行）
│   ├── export_books.py       # 数据库 → CSV
│   └── import_books.py       # CSV → 数据库
├── web/                       # Web 控制面板
│   ├── app.py                 # Flask 应用
│   └── templates/
│       └── index.html         # 控制面板页面
├── tests/
│   ├── test_parsers.py
│   ├── test_spiders.py
│   ├── test_db_pipeline.py
│   └── fixtures/             # 本地 HTML 样本
├── analysis/
│   └── visualize.py          # matplotlib 可视化
├── quality_checks.py         # 数据质量检查
└── dangdang_scrapy/
    ├── settings.py
    ├── items.py
    ├── pipelines.py
    ├── middlewares.py
    ├── db.py                 # 统一数据库连接 + upsert
    ├── parsers.py            # 集中解析函数
    └── spiders/
        ├── dangdang.py       # 列表爬虫（标准页 + 促销页）
        └── dangdang_detail.py # 详情页评分补抓
```

## 为什么不用 Makefile

项目自带的 `Makefile` 为 Linux/macOS 编写，硬编码了 Unix 路径（如 `bin/python`、`bin/pip`、`conda.sh`），在 Windows 上无法使用。Windows 用户需要手动执行以下等价命令。

---

## 环境要求

| 工具 | 安装方式 |
|------|---------|
| Miniconda / Anaconda | https://docs.anaconda.com/miniconda/ |
| Docker Desktop | https://www.docker.com/products/docker-desktop/ |
| Git Bash（推荐） | `winget install Git.Git` |

所有终端命令在 **Git Bash** 中执行。

> **PowerShell 用户注意**：`PYTHONPATH=.` 是 Bash 语法，PowerShell 中需写成 `$env:PYTHONPATH="."`。例如：
> ```powershell
> # PowerShell
> $env:PYTHONPATH="." ; python web/app.py
> ```
> ```bash
> # Git Bash（推荐）
> PYTHONPATH=. python web/app.py
> ```
> 下文中所有 `PYTHONPATH=.` 开头的命令都遵循此规则。

---

## 快速开始

### 第一步：创建 Conda 环境

```bash
conda create -n dangdang_scrapy python=3.13 -y
```

### 第二步：配置环境变量

```bash
cp .env.example .env
```

`.env` 默认内容可直接使用，无需修改：

```
DATABASE_URL=postgresql+psycopg2://dangdang:dangdang@localhost:5433/dangdang_books
PG_USER=dangdang
PG_PASSWORD=dangdang
PG_DB=dangdang_books
DANGDANG_USE_PLAYWRIGHT=false
```

### 第三步：安装 Python 依赖

```bash
# 激活环境并安装
conda activate dangdang_scrapy
pip install -r requirements.txt

# 如果启用 Playwright 模式，还需安装浏览器
playwright install chromium
```

> **提示**：如果 `conda activate` 在 Git Bash 中不生效，可以用 `conda run -n dangdang_scrapy` 前缀替代。后续命令均提供两种写法。

### 第四步：启动 PostgreSQL

```bash
docker compose up -d
```

验证容器运行正常：

```bash
docker ps --filter "name=dangdang-pg"
# 应看到 STATUS: Up ...
```

### 第五步：初始化数据库

```bash
# 方式一：conda activate 后直接运行
conda activate dangdang_scrapy
python -c "from dangdang_scrapy.db import init_db; init_db()"

# 方式二：用 conda run
conda run -n dangdang_scrapy python -c "from dangdang_scrapy.db import init_db; init_db()"
```

如果输出没有报错，说明建表成功。

---

## 数据采集

### 列表页抓取

```bash
# 激活 conda 环境后运行（推荐）
conda activate dangdang_scrapy
python -m scrapy crawl dangdang -s JOBDIR=jobs/crawl

# 首次测试：限制抓取数量
python -m scrapy crawl dangdang -s JOBDIR=jobs/crawl -s CLOSESPIDER_ITEMCOUNT=50
```

采集字段：书名、作者、出版社、价格、原价、评分、评论数、详情链接。

> **数据去向：** 数据实时写入 PostgreSQL 数据库，本地不产生文件。运行完可用下方 [如何查看数据库](#如何查看数据库) 或 [导出 CSV](#导出-csv) 查看结果。爬虫状态保存在 `jobs/crawl/` 目录，中断后下次运行可断点续抓。

### 详情页评分补抓

列表抓取完成后，补充缺失的评分和评论数：

```bash
conda activate dangdang_scrapy
python -m scrapy crawl dangdang_detail -s JOBDIR=jobs/detail
```

> 此命令会从数据库拉出评分缺失的商品，逐一访问详情页补全 `rating` 和 `rating_people`。更新结果直接写回数据库，不产生本地文件。

---

## 如何查看数据库

数据存储在 Docker 容器内的 PostgreSQL 中。以下几种方式都可以查看：

### 方式一：命令行 psql（最快捷）

```bash
docker compose exec postgres psql -U dangdang -d dangdang_books
```

进入 psql 后常用命令：

```sql
-- 查看总条数
SELECT COUNT(*) FROM books;

-- 查看最近 10 条
SELECT id, name, price, rating, detail_url FROM books ORDER BY id DESC LIMIT 10;

-- 查看某个字段的统计
SELECT ROUND(AVG(rating)::numeric, 1) AS 均分, MAX(price) AS 最高价 FROM books;

-- 退出
\q
```

### 方式二：Python 一行查询

```bash
conda activate dangdang_scrapy
python -c "from dangdang_scrapy.db import get_engine; from sqlalchemy import text; import pandas as pd; e=get_engine(); df=pd.read_sql('SELECT * FROM books ORDER BY id DESC LIMIT 10', e); print(df.to_string())"
```

### 方式三：VS Code PostgreSQL 插件（最方便，已在编辑器中）

**安装 & 连接步骤：**

1. 打开 VS Code 扩展市场（`Ctrl+Shift+X`），搜索 **PostgreSQL**，安装 `ms-ossdata.vscode-postgresql`

2. 安装后左侧会出现数据库图标（圆筒形），点击 → **Create Connection**

3. 填入连接参数：

   | 字段 | 值 |
   |------|-----|
   | Name | `dangdang_books`（随意起名） |
   | Host | `localhost` |
   | Port | `5433` |
   | Username | `dangdang` |
   | Password | `dangdang` |
   | The database to connect to... | 留空即可（留空会列出所有数据库，填入 `dangdang_books` 则直接进入） |
   | Connection String | 不填 |

4. 点击 **Connect**，连接成功后展开 `dangdang_books` → `Tables` → `books` → 右键 → **Select Top 1000**，即可浏览数据

5. 也可右键数据库 → **New Query**，直接写 SQL 查询

> 连接参数来自 `.env` 中的 `DATABASE_URL`：`postgresql+psycopg2://dangdang:dangdang@localhost:5433/dangdang_books`

### 方式四：其他图形化工具

| 工具 | 下载 | 特点 |
|------|------|------|
| DBeaver（免费） | https://dbeaver.io/download/ | 功能最全，支持多种数据库 |
| pgAdmin 4 | https://www.pgadmin.org/download/ | PostgreSQL 官方工具 |

连接参数与上方 VS Code 插件完全一致。

---

## 导出与分析

**重要：** Windows 上运行项目脚本时，Python 不会自动将项目根目录加入模块搜索路径，需要设置 `PYTHONPATH`。

定义一条别名可以让后续命令更方便（在 Git Bash 中执行一次）：

```bash
alias pyrun='PYTHONPATH=. PYTHONIOENCODING=utf-8 python'
```

### 质量报告

纯控制台输出，不产生文件。

```bash
conda activate dangdang_scrapy
PYTHONPATH=. python quality_checks.py
```

输出示例：

```
采集总条数: 8599
唯一商品(去重): 8599
可用详情页(product.dangdang.com): 7541 (87.7%)
评分补全率: 989/8599 (11.5%)
脏链接过滤(jump.php): 1058 (12.3%)
价格可解析率: 8175/8599 (95.1%)
书名非空率: 7694/8599 (89.5%)
```

### 导出 CSV

将数据库内容导出为 CSV 文件：

```bash
PYTHONPATH=. python scripts/export_books.py
# 输出: Exported 8599 rows to data/books.csv
```

**产出文件**：[`data/books.csv`](data/books.csv) — 可用 Excel、WPS 或 VS Code 直接打开查看。

### 导入 CSV

如果有历史 CSV 数据需要恢复到数据库：

```bash
PYTHONPATH=. python scripts/import_books.py
```

> 数据写入 PostgreSQL，不产生本地文件。

### 可视化

```bash
# 从数据库读取
PYTHONPATH=. python analysis/visualize.py

# 或从 CSV 读取
PYTHONPATH=. python analysis/visualize.py --csv data/books.csv
```

**产出文件**（位于 [`analysis/`](analysis/) 目录）：

| 文件 | 内容 |
|------|------|
| `analysis/price_distribution.png` | 价格分布直方图 + 箱线图 |
| `analysis/top_publishers.png` | 热门出版社 Top15 横向柱状图 |
| `analysis/rating_vs_price.png` | 价格 vs 评分散点图 |
| `analysis/sales_distribution.png` | 评论数分布 + Top10 |

> **已知问题**：图表中文字体硬编码为 `WenQuanYi Micro Hei`，Windows 系统不自带。中文图例会显示为方块。可以安装该字体或等后续适配微软雅黑。

---

## Web 控制面板

项目内置了一个 Web 界面，可以在浏览器中控制爬虫、筛选数据和查看可视化图表。

### 启动

```bash
# Git Bash（推荐）
conda activate dangdang_scrapy
PYTHONPATH=. python web/app.py
```
```powershell
# PowerShell
conda activate dangdang_scrapy
$env:PYTHONPATH="." ; python web/app.py
```

启动后浏览器打开 **http://127.0.0.1:5000**。

### 功能介绍

| 模块 | 说明 |
|------|------|
| 爬虫控制 | 设置抓取条数 → 点击「列表抓取」或「详情补抓」→ 实时显示运行状态 |
| 数据表格 | 浏览所有采集数据，支持分页 |
| 筛选条件 | 按书名/作者/出版社（模糊搜索）、评分区间、价格区间、评论人数筛选 |
| 排序 | 点击表头「价格」「评分」「评论数」可升降序排列 |
| 图表 | ECharts 渲染：评分分布、价格分布、出版社 Top10、价格 vs 评分散点图 |
| 导出 | 点击「导出 CSV」下载当前筛选结果为 CSV |

---

## 验证与测试

### 运行单元测试

```bash
conda activate dangdang_scrapy

# 仅单元测试（不依赖数据库）
pytest tests/ -v -m "not integration"

# 全部测试（需要测试数据库）
pytest tests/ -v
```

### 运行集成测试

```bash
# 1. 创建测试库
docker compose exec postgres psql -U dangdang -c \
  "CREATE DATABASE dangdang_books_test WITH TEMPLATE template0 ENCODING 'UTF8'" 2>/dev/null || true

# 2. 运行集成测试
TEST_DATABASE_URL=postgresql+psycopg2://dangdang:dangdang@localhost:5433/dangdang_books_test \
  pytest tests/ -v --tb=short
```

---

## Makefile 命令对照表

| Linux/macOS (`make`) | Windows 等价命令 | 数据产出 |
|---|---|---|
| `make setup` | 见上方"快速开始"第三步~第五步 | PostgreSQL 数据库 |
| `make crawl` | `python -m scrapy crawl dangdang -s JOBDIR=jobs/crawl` | PostgreSQL + `jobs/crawl/`（进度） |
| `make detail` | `python -m scrapy crawl dangdang_detail -s JOBDIR=jobs/detail` | PostgreSQL（更新评分） |
| `make export` | `PYTHONPATH=. python scripts/export_books.py` | `data/books.csv` |
| `make import` | `PYTHONPATH=. python scripts/import_books.py` | PostgreSQL |
| `make analyze` | `PYTHONPATH=. python analysis/visualize.py` | `analysis/*.png`（4 张） |
| `make quality` | `PYTHONPATH=. python quality_checks.py` | 控制台输出 |
| `make verify-fast` | `pytest tests/ -v -m "not integration"` | 控制台输出 |
| `make test-full` | 见上方"运行集成测试" | 控制台输出 |
| `make reset-db` | `docker compose down -v && docker compose up -d` 然后重新 `init_db()` | 清空数据库 |
| `make web` | `PYTHONPATH=. python web/app.py` | Web 控制面板 → http://127.0.0.1:5000 |
| `make psql` | `docker compose exec postgres psql -U dangdang -d dangdang_books` | 交互式 SQL 终端 |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | 必填 | PostgreSQL 连接串 |
| `DANGDANG_USE_PLAYWRIGHT` | `false` | `true` 时启用 Playwright 渲染 |
| `PG_USER` / `PG_PASSWORD` / `PG_DB` | dangdang | Docker Compose 变量 |

## 双模式渲染

| 模式 | 速度 | 抗反爬 | 设置 |
|------|------|--------|------|
| 原生 HTTP | ~0.3s/页 | 中等 | `DANGDANG_USE_PLAYWRIGHT=false`（默认） |
| Playwright | ~3s/页 | 最强 | `DANGDANG_USE_PLAYWRIGHT=true` |

## 字段语义

| 字段 | 类型 | 说明 |
|------|------|------|
| `rating` | DOUBLE (0–100) | **百分比值**，90 = 4.5 星，非 5 分制 |
| `rating_people` | BIGINT | 评论人数，可为空 |
| `price` | DOUBLE | 当前售价，可为空 |
| `sales` | BIGINT | 销量（当前未采集），保留字段 |

## 数据流

```
当当网 → Scrapy spider → BookCleaningPipeline → DatabasePipeline(upsert) → PostgreSQL
                                                                             ↓
                                                                      CSV（显式导出）
                                                                             ↓
                                                                  matplotlib（可视化）
```

## 开发者指南

### 新增解析函数
1. 在 [parsers.py](dangdang_scrapy/parsers.py) 实现，补类型标注
2. 在 [tests/test_parsers.py](tests/test_parsers.py) 补测试（正常值 / 空值 / 异常值）
3. 在 `pipelines.py` 或 `spiders/` 中复用

### 新增爬虫 / Fixture / 集成测试
1. 爬虫放在 `spiders/`，数据库测试打 `@pytest.mark.integration`
2. 本地 HTML fixture 放在 `tests/fixtures/`，测试不依赖外网
3. 集成测试使用 `TEST_DATABASE_URL`（必须以 `_test` 结尾），与生产库隔离

### 数据语义

| 字段 | 说明 |
|------|------|
| `rating` | 百分比 0-100，90 = 4.5 星 |
| `rating_people` | 评论数，可为空 |
| `sales` | 预留字段，当前未采集 |
| `price` | 当前售价，可为空 |

## 常见问题

### conda activate 在 Git Bash 中不生效

运行 `conda init bash` 后重启终端，或使用 `conda run -n dangdang_scrapy` 前缀替代。

### ModuleNotFoundError: No module named 'dangdang_scrapy'

添加 `PYTHONPATH=.` 环境变量。Python 3.13 不再自动将当前目录加入搜索路径。

### 中文输出乱码

添加 `PYTHONIOENCODING=utf-8` 环境变量。

### 图表中文显示为方块

缺少中文字体。临时方案：用 `--csv` 参数读取数据后在其他工具绘图。根治方案：修改 [visualize.py](analysis/visualize.py) 使用 Windows 系统自带的 `Microsoft YaHei`。

## 技术栈

Python 3.13 · Scrapy 2.15 · Playwright · PostgreSQL 16 · Docker · Conda · pandas · matplotlib

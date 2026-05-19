export DATABASE_URL ?= $(shell grep ^DATABASE_URL .env 2>/dev/null | cut -d= -f2-)
export DANGDANG_USE_PLAYWRIGHT ?= $(shell grep ^DANGDANG_USE_PLAYWRIGHT .env 2>/dev/null | cut -d= -f2-)
PG_USER   ?= $(shell grep ^PG_USER .env 2>/dev/null | cut -d= -f2-)
PG_USER   ?= dangdang
PG_PASS   ?= $(shell grep ^PG_PASSWORD .env 2>/dev/null | cut -d= -f2-)
PG_PASS   ?= dangdang
PG_DB     ?= $(shell grep ^PG_DB .env 2>/dev/null | cut -d= -f2-)
PG_DB     ?= dangdang_books

# Conda 环境配置
CONDA_ENV  ?= dangdang_scrapy
CONDA_BASE := $(shell conda info --base 2>/dev/null || echo "$(HOME)/miniconda3")
PYTHON      = $(CONDA_BASE)/envs/$(CONDA_ENV)/bin/python
PIP         = $(CONDA_BASE)/envs/$(CONDA_ENV)/bin/pip
CONDA_RUN   = . "$(CONDA_BASE)/etc/profile.d/conda.sh" && conda activate $(CONDA_ENV)

define wait_pg
	@echo "等待 PG 就绪..."
	@for i in 1 2 3 4 5 6 7 8; do \
		PGPASSWORD=$(PG_PASS) docker compose exec -T postgres pg_isready -U $(PG_USER) -q 2>/dev/null && break; \
		if [ $$i -eq 8 ]; then echo "PG 启动超时"; exit 1; fi; \
		echo "  等待中... ($$i)"; \
		sleep 2; \
	done
	@sleep 1
endef

.PHONY: setup crawl detail export analyze verify-fast verify-e2e quality test-full reset-db web

setup:
	$(PIP) install -r requirements.txt
	$(CONDA_RUN) && playwright install chromium 2>/dev/null || true
	[ -f .env ] || cp .env.example .env
	docker compose up -d
	$(call wait_pg)
	$(PYTHON) -c "from dangdang_scrapy.db import init_db; init_db()"
	@echo ""
	@echo "环境就绪！"
	@echo "  make crawl      列表抓取"
	@echo "  make detail     评分补抓"
	@echo "  make import     导入旧CSV (可选)"
	@echo "  make export     导出CSV"
	@echo "  make analyze    可视化"
	@echo "  make quality    数据质量报告"
	@echo "  make verify-fast 快速验证 (fixture测试+冒烟)"
	@echo "  make verify-e2e 端到端验证 (含运行时断言)"

import: data/books.csv
	$(PYTHON) scripts/import_books.py

crawl:
	$(PYTHON) -m scrapy crawl dangdang -s JOBDIR=jobs/crawl

detail:
	$(PYTHON) -m scrapy crawl dangdang_detail -s JOBDIR=jobs/detail

export:
	$(PYTHON) scripts/export_books.py

analyze:
	$(PYTHON) analysis/visualize.py

quality:
	$(PYTHON) quality_checks.py

verify-fast: quality
	$(PYTHON) -m pytest tests/ -v --tb=short -m "not integration"
	@echo ""
	@echo "=== 导出冒烟 ==="
	$(PYTHON) scripts/export_books.py
	@echo ""
	@echo "=== 分析冒烟 ==="
	@if [ -f data/books.csv ]; then \
		$(PYTHON) analysis/visualize.py --csv data/books.csv; \
	else \
		echo "data/books.csv 不存在，跳过分析冒烟"; \
	fi
	@echo ""
	@echo "快速验证通过！"

verify-e2e: verify-fast
	@echo ""
	@echo "=== 运行时断言 ==="
	$(PYTHON) scripts/assert_runtime_state.py
	@echo ""
	@echo "端到端验证通过！"

test-full:
	@echo "=== 准备测试库 ==="
	@PGPASSWORD=$(PG_PASS) docker compose exec -T postgres psql -U $(PG_USER) -c \
		"CREATE DATABASE dangdang_books_test WITH TEMPLATE template0 ENCODING 'UTF8'" 2>/dev/null || true
	@echo "=== 运行集成测试 (TEST_DATABASE_URL=dangdang_books_test) ==="
	TEST_DATABASE_URL=postgresql+psycopg2://$(PG_USER):$(PG_PASS)@localhost:5433/dangdang_books_test \
		$(PYTHON) -m pytest tests/ -v --tb=short

reset-db:
	docker compose down -v
	docker compose up -d
	$(call wait_pg)
	$(PYTHON) -c "from dangdang_scrapy.db import init_db; init_db()"

web:
	$(PYTHON) web/app.py

psql:
	docker compose exec postgres psql -U $(PG_USER) -d $(PG_DB)

logs:
	tail -f data/*.log

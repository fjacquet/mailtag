# MailTag Development Makefile — fjacquet/ci standard interface (do not rename canonical targets)
.DEFAULT_GOAL := all
DIST ?= dist

.PHONY: all clean install tools lint format test build vuln sbom security docs coverage-upload release ci dev

all: clean lint test build

clean:
	rm -rf $(DIST) site .coverage coverage.xml *.sarif
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

install:
	uv sync --all-extras --all-groups

tools: install

# Run the application
dev:
	uv run python -m mailtag

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

test:
	uv run pytest --cov --cov-report=xml --cov-report=term-missing

build:
	uv build

vuln:
	uvx osv-scanner scan --lockfile=uv.lock || true

sbom:
	mkdir -p $(DIST)
	uv run cyclonedx-py environment --output-format JSON --output-file $(DIST)/sbom.cdx.json

security:  # advisory: reports findings but never blocks the build (CodeQL/osv are the blocking gates)
	uvx semgrep scan --config auto --skip-unknown-extensions || true

docs:
	uv run mkdocs build --strict --site-dir site

coverage-upload:
	uvx --from codecov-cli codecov upload-process --file coverage.xml || true

release:
	uv build
	uv publish --trusted-publishing always

ci: lint test build

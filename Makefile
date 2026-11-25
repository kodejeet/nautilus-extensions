SHELL := /bin/bash
PYTHON ?= python3
RUFF ?= ruff

.PHONY: help test lint format check install uninstall doctor release clean

help:
	@printf '%s\n' \
		'Nautilus Extensions' \
		'' \
		'  make test       Run the headless test suite' \
		'  make lint       Check formatting, lint, and shell syntax' \
		'  make format     Apply Ruff formatting and safe fixes' \
		'  make check      Lint + tests' \
		'  make install    Per-user install from this checkout' \
		'  make uninstall  Remove the per-user install' \
		'  make doctor     Print environment diagnostics' \
		'  make release    Build dist/ tarball + checksum' \
		'  make clean      Remove local caches and build outputs'

test:
	$(PYTHON) -m pytest -q

lint:
	$(RUFF) check .
	$(RUFF) format --check .
	bash -n install.sh uninstall.sh scripts/*.sh

format:
	$(RUFF) format .
	$(RUFF) check --fix .

check: lint test

install:
	./install.sh

uninstall:
	./uninstall.sh

doctor:
	./scripts/doctor.sh

release:
	./scripts/package.sh

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache build dist
	rm -rf __pycache__ extensions/__pycache__ tests/__pycache__ tests/stubs/gi/__pycache__ tests/stubs/gi/repository/__pycache__
	find . -name '*.pyc' -delete

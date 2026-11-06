VENV   ?= .venv
PYTHON ?= $(VENV)/bin/python

.PHONY: setup build lint test check lock clean

setup: ## create .venv and install pinned dependencies
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -q -r requirements-dev.txt

build: ## run steps 1-4 on the example spec for every locale -> build/
	$(PYTHON) run_pipeline.py

lint: ## ruff lint and format check
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

test: ## unit tests plus the end-to-end pipeline tests
	$(PYTHON) -m pytest

check: lint test ## everything CI runs

lock: ## re-pin requirements*.txt from pyproject.toml (needs uv)
	uv pip compile pyproject.toml --universal --python-version 3.10 --no-header -o requirements.txt
	uv pip compile pyproject.toml --extra dev --universal --python-version 3.10 --no-header -o requirements-dev.txt

clean:
	rm -rf build .pytest_cache .ruff_cache __pycache__ tests/__pycache__

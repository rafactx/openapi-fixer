VENV   ?= .venv
PYTHON ?= $(VENV)/bin/python

.PHONY: setup build check clean

setup: ## create .venv and install dependencies
	python3 -m venv $(VENV)
	$(PYTHON) -m pip install -q -r requirements-dev.txt

build: ## run steps 1-4 on the example spec for every locale -> build/
	$(PYTHON) run_pipeline.py

check: ## run the pipeline end to end and validate every output
	$(PYTHON) -m pytest -q

clean:
	rm -rf build .pytest_cache __pycache__ tests/__pycache__

PYTHON ?= python3
VENV ?= .venv

.PHONY: setup test test-storage check setup-web test-web build-web

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -e apps/photoflow

test:
	cd apps/photoflow && $(PYTHON) -m unittest discover -v

# Set PHOTOFLOW_STORAGE_TEST_ROOT to exercise a specific mounted filesystem.
test-storage:
	cd apps/photoflow && $(PYTHON) -m unittest tests.test_storage -v

check: test
	cd apps/photoflow && $(PYTHON) -m photoflow --help

setup-web: setup
	$(VENV)/bin/pip install -r apps/web/requirements.lock
	$(VENV)/bin/pip install -e apps/web
	cd apps/web/ui && npm ci

test-web:
	PYTHONPATH=apps/web:apps/photoflow $(PYTHON) -m unittest discover -s apps/web/tests -v

build-web:
	cd apps/web/ui && npm run build -- --outDir ../photoflow_web/static --emptyOutDir

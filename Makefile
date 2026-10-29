PYTHON ?= python3
VENV ?= .venv

.PHONY: setup test test-storage check

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

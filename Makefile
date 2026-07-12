# NybiScan build orchestration.
#
# One command surface across both toolchains: the Python core/api/cli
# (src/nybiscan, pytest) and the macOS Swift GUI (gui/, swift test). These
# targets WRAP the existing mechanisms (pip, swift, gui/scripts/make_app.sh);
# they do not reimplement them. Targets reference .venv/bin/* explicitly so they
# work whether or not the venv is activated.

VENV := .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
NYBISCAN := $(VENV)/bin/nybiscan
APP := gui/NybiScan.app

.PHONY: help setup test test-python test-swift build run clean clean-all

help:
	@echo "NybiScan make targets:"
	@echo "  make setup      create .venv at the repo root + install deps + resolve SwiftPM"
	@echo "  make test       run both suites (pytest + swift test)"
	@echo "  make build      swift build + bundle NybiScan.app"
	@echo "  make run        launch the built app"
	@echo "  make clean      remove build artifacts (keeps .venv)"
	@echo "  make clean-all  also remove .venv"

# Create the Python environment at the EXACT repo-root path named .venv (the
# GUI locates the core at <repo>/.venv/bin/nybiscan), install the package with
# dev extras, and resolve SwiftPM (a no-op today: no external Swift deps).
setup:
	python3 -m venv $(VENV)
	$(PIP) install -e ".[dev]"
	cd gui && swift package resolve

test: test-python test-swift

test-python:
	$(PYTEST) -q

test-swift:
	cd gui && swift test

# swift build then bundle the clickable app via the existing script.
build:
	cd gui && swift build
	cd gui && ./scripts/make_app.sh

# Fail fast (mirroring the app's own contract) if the core env or app is missing.
run:
	@test -x "$(NYBISCAN)" || { echo "NybiScan core not found at $(NYBISCAN). Run 'make setup' first."; exit 1; }
	@test -d "$(APP)" || { echo "$(APP) is not built. Run 'make build' first."; exit 1; }
	open "$(APP)"

clean:
	rm -rf gui/.build "$(APP)"
	rm -rf .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

clean-all: clean
	rm -rf $(VENV)

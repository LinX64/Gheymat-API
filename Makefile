.PHONY: help test test-verbose test-coverage test-fast install clean lint format security

help:
	@echo "Currency Cap Portal - Development Commands"
	@echo ""
	@echo "Available commands:"
	@echo "  make install        - Install all dependencies including test dependencies"
	@echo "  make test          - Run all tests"
	@echo "  make test-verbose  - Run tests with verbose output"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make test-fast     - Run tests without slow tests"
	@echo "  make test-html     - Run tests and generate HTML coverage report"
	@echo "  make lint          - Run code linting"
	@echo "  make format        - Format code with black and isort"
	@echo "  make security      - Run security checks"
	@echo "  make clean         - Clean up cache and temporary files"
	@echo "  make update-apis   - Update all API data"

install:
	pip install --upgrade pip
	pip install -r requirements.txt

test:
	pytest

test-verbose:
	pytest -v

test-coverage:
	pytest --cov=. --cov-report=term-missing

test-html:
	pytest --cov=. --cov-report=html
	@echo "Coverage report generated in htmlcov/index.html"

test-fast:
	pytest -m "not slow"

test-watch:
	pytest-watch

lint:
	@echo "Running flake8..."
	flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics --exclude=tests,venv,.venv,env,.env
	flake8 . --count --max-complexity=10 --max-line-length=120 --statistics --exclude=tests,venv,.venv,env,.env
	@echo "Running black check..."
	black --check --exclude='/(\.git|\.venv|venv|env|\.env|__pycache__|\.pytest_cache|htmlcov)/' .
	@echo "Running isort check..."
	isort --check-only --skip .venv --skip venv --skip env --skip .env .

format:
	@echo "Formatting with black..."
	black --exclude='/(\.git|\.venv|venv|env|\.env|__pycache__|\.pytest_cache|htmlcov)/' .
	@echo "Sorting imports with isort..."
	isort --skip .venv --skip venv --skip env --skip .env .

security:
	@echo "Checking dependencies for security issues..."
	safety check || true
	@echo "Running security analysis with bandit..."
	bandit -r . --exclude './tests,./venv,./.venv,./env,./.env' || true

clean:
	@echo "Cleaning up..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".coverage" -delete
	rm -rf htmlcov/
	rm -rf .coverage
	rm -rf coverage.xml
	rm -rf .pytest_cache/
	@echo "Clean complete!"

update-apis:
	python update_apis.py

# Run specific test file
test-helper:
	pytest tests/test_helper.py -v

test-cache:
	pytest tests/test_cache.py -v

test-updaters:
	pytest tests/test_updaters.py -v

test-apis:
	pytest tests/test_APIs.py -v

test-generate:
	pytest tests/test_generate_history_date.py -v

test-update-apis:
	pytest tests/test_update_apis.py -v

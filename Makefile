.PHONY: lint test clean coverage all

lint:
	python -m ruff check .

test:
	python -m pytest tests/ -q --tb=short

coverage:
	python -m pytest tests/ -q --tb=short --cov=src/emsal_mcp --cov-report=term-missing

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov

all: lint test

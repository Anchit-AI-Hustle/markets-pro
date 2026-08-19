.PHONY: test verify lint demo serve screen quality clean

PY ?= python3

test:                ## Run the full test suite
	$(PY) -m unittest discover -s tests -t . -v

verify:              ## Run the suite and print the accuracy report
	$(PY) verify.py

lint:
	ruff check src tests

quality:             ## Verify live cache freshness & sanity
	PYTHONPATH=src $(PY) -m autotrader.data.quality --data data/live

screen:              ## Screen the live universe, print snapshot to stdout
	PYTHONPATH=src $(PY) -m autotrader.screener.core --data data/live

demo:                ## Run the multi-region backtest demo
	PYTHONPATH=src $(PY) examples/demo.py

dashboard:           ## Build the static dashboard into out/
	PYTHONPATH=src $(PY) examples/build_dashboard.py

serve:               ## Serve the dashboard at http://localhost:8000/markets-pro
	PYTHONPATH=src $(PY) -m autotrader.web.server

clean:
	rm -rf out reports .ruff_cache **/__pycache__

.PHONY: test verify lint demo serve clean

PY ?= python3

test:                ## Run the full test suite
	$(PY) -m unittest discover -s tests -t . -v

verify:              ## Run the suite and print the accuracy report
	$(PY) verify.py

lint:
	ruff check src tests

demo:                ## Run the multi-region backtest demo
	PYTHONPATH=src $(PY) examples/demo.py

dashboard:           ## Build the static dashboard into out/
	PYTHONPATH=src $(PY) examples/build_dashboard.py

serve:               ## Serve the dashboard at http://localhost:8000/markets-pro
	PYTHONPATH=src $(PY) -m autotrader.web.server

clean:
	rm -rf out reports .ruff_cache **/__pycache__

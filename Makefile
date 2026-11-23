.PHONY: install test eval charts run
install: ; pip install -r requirements.txt
test:    ; python -m pytest -q
eval:    ; python -m evals.run_evals
charts:  ; python scripts/make_charts.py
run:     ; uvicorn app.api:api --reload

# Convenience wrapper for the ffrank pipeline. Run from pipeline/.
# Uses the project venv and puts src/ on the path so `python -m ffrank.*` just works.
PY := .venv/bin/python
export PYTHONPATH := src

SEASON  ?= 2026
SCORING ?= ppr

.PHONY: help board gate test probe
help:
	@echo "make board [SEASON=2026] [SCORING=ppr|half|standard]  build + print the board, write JSON"
	@echo "                                                       (applies committed soft ratings;"
	@echo "                                                        add --no-soft via ffrank.rank to skip)"
	@echo "make gate                                             run the retro-validation gate"
	@echo "make test                                             run pytest"
	@echo "make probe [SEASON=2024]                              print live nflreadpy schemas"

board:
	$(PY) -m ffrank.rank --season $(SEASON) --scoring $(SCORING)

gate:
	$(PY) -m ffrank.validate

test:
	$(PY) -m pytest -q

probe:
	$(PY) -m ffrank.probe $(SEASON)

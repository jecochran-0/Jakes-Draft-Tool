# Convenience wrapper for the ffrank pipeline. Run from pipeline/.
# Uses the project venv and puts src/ on the path so `python -m ffrank.*` just works.
PY := .venv/bin/python
export PYTHONPATH := src

SEASON  ?= 2026
SCORING ?= ppr
SCORES  ?= data/soft_scores.json

.PHONY: help board gate test probe draft-table emit soft
help:
	@echo "make board [SEASON=2026] [SCORING=ppr|half|standard]  build + print the board, write JSON"
	@echo "make gate                                             run the retro-validation gate"
	@echo "make test                                             run pytest"
	@echo "make probe [SEASON=2024]                              print live nflreadpy schemas"
	@echo "make draft-table                                      emit team-table draft prompt (step A)"
	@echo "make emit [SEASON=2026]                               emit soft-signal player prompts (step B)"
	@echo "make soft SCORES=data/soft_scores.json                apply soft scores + re-rank (step C)"

board:
	$(PY) -m ffrank.rank --season $(SEASON) --scoring $(SCORING)

gate:
	$(PY) -m ffrank.validate

test:
	$(PY) -m pytest -q

probe:
	$(PY) -m ffrank.probe $(SEASON)

draft-table:
	$(PY) -m ffrank.softsignals draft-team-table

emit:
	$(PY) -m ffrank.rank --season $(SEASON) --emit-prompts --no-adp --no-write

soft:
	$(PY) -m ffrank.rank --season $(SEASON) --scoring $(SCORING) --soft-scores $(SCORES)

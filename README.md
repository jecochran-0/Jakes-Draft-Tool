# Jake's Draft Tool

Pre-draft fantasy football ranking tool for skill positions (QB/RB/WR/TE). Two parts that
communicate through one JSON file (`schema/contract.schema.json`):

- **Part A — `pipeline/`** (Python, offline): nflverse data → projected fantasy points → JSON.
- **Part B — `app/`** (Next.js, later slice): renders the four views from the JSON.

All four outputs (overall ranks, positional tiers, projected points, value-vs-ADP) are views
over **one number per player: projected fantasy points.** One projection engine; four views.

## Status

Decisions locked: **12-team / 1QB-2RB-2WR-1TE-1FLEX**, **Full PPR**.

### Slice 1 — Foundation + validation gate ✅
- Locked JSON contract (`schema/`) + pydantic models (`pipeline/src/ffrank/schema.py`).
- nflreadpy ingestion (column names verified at runtime via `ffrank.probe`).
- Configurable scoring; our PPR matches nflverse `fantasy_points_ppr` (tested).
- `base_points` projection: recency- & reliability-weighted per-game blend, rank-preserving
  baseline shrink, position age curves. Rookie branch via draft capital (excluded from gate).
- Replacement-level rule for VORP via greedy lineup fill (resolves spec §6c).
- **Retro-validation gate** (`ffrank.validate`): predicts 2025 from ≤2024 and 2024 from ≤2023,
  compares to actual `fantasy_points_ppr`. **Beats the naive last-season baseline on Spearman
  in all 8 position-folds** (ρ ≈ 0.63–0.78), with strong point calibration.

Known caveat (by design): at the very top (top-24), the blend is a wash with naive, and
slightly softer for WR — the most volatile position. Refining the volatile top is exactly the
job of the deferred **soft-signals** slice.

### Slice 2 — VORP / ranks / tiers ✅ (`pipeline/src/ffrank/ranking.py`)
- **VORP** = ranking-metric − replacement level (the greedy rule from slice 1). Makes positions
  comparable (value-based drafting): scarce-position studs rise, surplus QB points discount.
- **`overall_rank`** by VORP, **`position_rank`** within position, **positional tiers** by
  gap-detection on the draftable top of each position.
- Ranks on `base_points` today; auto-switches to `adjusted_points` once soft signals land
  (`ranking.ranking_metric`). The output JSON now populates vorp/ranks/tier (100%).

Deferred to later slices (fields reserved in the contract): Sleeper ADP + `value_vs_adp`
(needs `overall_rank`, now available), Vegas team totals, hand-curated team-situation table,
LLM soft-signals (prompt-emit + merge), and the Next.js app.

## Quickstart

```bash
cd pipeline
python3.12 -m venv .venv
.venv/bin/pip install nflreadpy polars pandas scipy pydantic requests pytest

# CLI modules are run with src on the path (no install step needed):
export PYTHONPATH=src

# Verify library column names against the live nflverse data:
.venv/bin/python -m ffrank.probe

# Run the validation gate (network; downloads nflverse data):
.venv/bin/python -m ffrank.validate

# Produce base_points rankings + a contract-shaped JSON for a season:
.venv/bin/python -m ffrank.rank --season 2026 --top 24
# -> pipeline/output/rankings_2026_ppr.json

# Tests read src/ via pyproject's pythonpath config — no PYTHONPATH needed:
.venv/bin/python -m pytest -q
```

## Layout

```
schema/        # contract.schema.json (locked) + sample.json
pipeline/
  src/ffrank/
    config.py       # league + scoring + replacement-level rule (§6c)
    schema.py       # pydantic models mirroring the contract
    probe.py        # runtime column-probe for nflreadpy
    ingest.py       # nflreadpy -> normalized PlayerHistory
    scoring.py      # component stats + ScoringConfig -> points
    project.py      # base_points engine (veteran blend + rookie branch)
    validate.py     # retro-validation gate + reports
    rank.py         # capstone: rankings + contract JSON
  reports/     # validation_<pos>_<season>.md / .csv
  output/      # rankings_<season>_<format>.json
app/           # Next.js (later slice)
```

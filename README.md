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

### Slice 3 — ADP / value-vs-ADP ✅ (`pipeline/src/ffrank/adp.py`)
- **`market` block**: `adp`, `adp_rank`, `value_vs_adp = adp_rank − overall_rank` (positive =
  market drafts him later than we rank him = steal). Populated for the full ~150-player
  draftable pool (152/153 matched by normalized name + position).
- **Source deviation (per the spec's own VERIFY clause):** the spec named Sleeper, but Sleeper
  has **no public ADP endpoint** (it gives leagues/drafts/players + stable ids only), and
  nflreadpy's `load_ff_rankings` is ECR, not ADP. We use **FantasyFootballCalculator's** free,
  no-key ADP API (PPR/Half/Standard, by team count) — real ADP over hundreds of drafts.
- Runs at build time inside `ffrank.rank`; never hard-fails on a network error (market stays
  null). `--no-adp` skips the fetch for fully-offline runs.
- Known caveat: `value_vs_adp` is only meaningful for draftable players. Rookies / 2nd-year
  breakout bets that the market drafts but the veteran stat-model ranks deep show large
  artifact magnitudes — the steals/reaches view bounds to our top 180 and counts the rest.

### Slice 4 — Rookie projections ✅ (`ingest.build_rookie_histories`, `project.project_rookie`)
- Incoming draft class from `load_draft_picks(season)` (skill positions), joined to
  `ff_playerids` for sleeper id + age; `is_rookie=True`, tagged in the output and board.
- **Position-aware** draft-capital anchors (year-1 fantasy value differs sharply by position):
  rookie RB/WR can produce immediately, rookie QBs score on a higher scale, rookie TEs rarely
  hit. Scaled by a neutral `opportunity_factor` (landing-spot/Vegas refinement deferred).
- Rookies flow through the same VORP → ranks → tiers → ADP pipeline as veterans. The model
  takes a conservative stat-anchored stance, so market-hyped rookies surface as ADP "reaches"
  by design — the soft-signals slice is where situational role/landing-spot judgment is added.

### Slice 5 — Vegas team totals ✅ (`pipeline/src/ffrank/vegas.py`)
- The Odds API exposes **game** totals + spreads, so we derive the implied **team total**
  (`game_total/2 − team_spread/2`), averaged over bookmakers and a team's posted games, mapped
  to nflverse abbreviations. Populates `situation.vegas_team_total`.
- Reads `THE_ODDS_API_KEY` from the environment; **skips gracefully** (leaves the field null,
  never hard-fails) when the key is unset. `--no-vegas` forces skip.
- Seasonality: per-game lines only exist preseason/in-season — a deep-offseason run returns no
  games and leaves totals null (expected). A pre-draft run in August picks up the early slate.
- Stored now as a signal; it gets **factored into `adjusted_points`** in the soft-signals slice
  (per spec §6b), which is intentionally last.

```bash
export THE_ODDS_API_KEY=your_key   # free tier at the-odds-api.com
.venv/bin/python -m ffrank.rank --season 2026   # now populates vegas_team_total
```

### Slice 6 — Soft signals → adjusted_points ✅ (`pipeline/src/ffrank/softsignals.py`)
Situational judgment (scheme, OC/QB changes, role) → a `soft_score` multiplier →
`adjusted_points = base × soft_score` → the board **re-ranks on adjusted** (VORP/tiers already
read it via `ranking.ranking_metric`). **Cost $0** — human-in-the-loop, no paid API.

Three copy-paste steps (all free):
```bash
# A. draft the 32-team situation table
python -m ffrank.softsignals draft-team-table     # -> output/prompts/team_table_prompt.txt
# paste into Claude -> save JSON to pipeline/data/team_situations.json (see *.sample.json)

# B. emit batched per-player prompts (system prompt §7c + facts, id-echo guardrail)
python -m ffrank.rank --season 2026 --emit-prompts # -> output/prompts/soft_batch_1..N.txt
# paste each into Claude -> concatenate JSON arrays into pipeline/data/soft_scores.json

# C. apply, re-rank on adjusted, audit, write final JSON
python -m ffrank.rank --season 2026 --soft-scores pipeline/data/soft_scores.json
```
- `soft_score` **clamped to [0.85, 1.15]** in Python regardless of LLM output (stats lead, judgment nudges).
- Vegas is an **LLM input fact only** (no separate multiplier) — resolves the §6b ambiguity.
- **Audit (§9):** the run prints the biggest base→adjusted moves with their reasoning.
- **LLM-off fallback (§9):** just omit `--soft-scores` → the board ranks on `base_points`.
- `data/*.sample.json` show the exact shapes; real files are the user's Claude output (committable).

**Part A (the projection pipeline) is now feature-complete** — all four headline views, plus the
optional soft-signals layer. Remaining: the **Next.js app (Part B)**, paused mid-scaffold.

## Quickstart

```bash
cd pipeline
python3.12 -m venv .venv
.venv/bin/pip install nflreadpy polars pandas scipy pydantic requests pytest
```

The `Makefile` wraps the common commands (sets `PYTHONPATH=src`, uses the venv):

```bash
make board                       # build + print the draft board, write the JSON
make board SCORING=half          # Half-PPR (also: standard) -> rankings_2026_half.json
make board SEASON=2025           # any season
make gate                        # retro-validation gate (downloads nflverse data)
make test                        # pytest
make probe SEASON=2024           # print live nflreadpy schemas
make help                        # all targets
```

**Scoring formats (spec §2 — one file per format):** `--scoring ppr|half|standard` (default `ppr`)
re-scores receptions and writes `rankings_<season>_<format>.json`. The ADP join auto-matches the
same format.

Raw commands (equivalent, if you'd rather not use `make`):

```bash
export PYTHONPATH=src
.venv/bin/python -m ffrank.rank --season 2026 --scoring ppr --top 24
.venv/bin/python -m ffrank.validate
.venv/bin/python -m pytest -q     # (tests don't need PYTHONPATH; pyproject handles it)
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

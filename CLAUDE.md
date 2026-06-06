# CLAUDE.md

Guidance for working in this repo. Keep it accurate — update it when the architecture changes.

## Project

Pre-draft **fantasy football ranking tool**, skill positions only (QB/RB/WR/TE — no DST/kickers).
Produces four views over **one number per player (projected fantasy points)**: overall ranks,
positional tiers, projected points, and value-vs-ADP. Build one projection engine; derive the
four views from it — do not build four separate features.

Locked decisions: **12-team, 1QB/2RB/2WR/1TE/1FLEX**, **Full PPR** default (half/standard also
supported). **Cost target $0** (no paid APIs; the LLM step is manual copy-paste, not the API).

## Architecture — two parts, one JSON contract

The contract is `schema/contract.schema.json`. Lock it first; both parts hang off it.

- **Part A — `pipeline/`** (Python, offline): nflverse data → projected points → JSON. The
  pipeline is **offline/committed**, never run on a server (Vercel only serves the static JSON).
- **Part B — `app/`** (Next.js on Vercel): renders the JSON. **Not built yet** — `app/` is a
  paused scaffold (`package.json` + `node_modules` only) and is intentionally **uncommitted**.

## Running Part A

Requires **Python 3.12** (system `python3` is 3.9 — too old for `nflreadpy`, which needs ≥3.10).
The venv lives at `pipeline/.venv`. Run everything from `pipeline/` via the Makefile:

```
make board [SEASON=2026] [SCORING=ppr|half|standard]   # build + print board, write JSON
make gate            # retro-validation gate
make test            # pytest
make probe [SEASON=2024]   # print LIVE nflreadpy schemas (verify columns before coding)
make draft-table     # soft-signals step A (emit team-table prompt)
make emit            # soft-signals step B (emit batched player prompts)
make soft SCORES=data/soft_scores.json   # step C (apply + re-rank)
```

Modules run with `PYTHONPATH=src` (the Makefile sets it). **`pip install -e .` is flaky here**
(setuptools strict-editable doesn't register on this machine) — prefer `PYTHONPATH=src`. Tests
get `src/` via `pyproject.toml`'s `pythonpath`, so `make test` needs no env.

## Ranking model — how the signals combine (keep them non-overlapping)

- **`base_points`** = stats (veterans: recency+reliability-weighted per-game blend → 17 games →
  age curve) or draft capital (rookies, scaled per scoring format). The foundation.
- **`adjusted_points = base × vegas_mult × soft_mult`** — computed in **one place**,
  `vegas.finalize_adjusted`:
  - **Vegas tilt** (±8%, clamped) applies **only to rookies + team-changers**
    (`vegas.new_env_player_ids` — players whose current environment isn't in their stats).
    Stay-put veterans are untouched, so Vegas never double-counts offense already in their points.
    Vegas is therefore **not** in the LLM prompt either.
  - **`soft_score`** (manual LLM, clamped ±15%) = scheme / coaching / QB / role only.
  - If neither applies, `adjusted` stays null → the board ranks on `base_points` (LLM-off
    fallback). Vegas is null in the deep offseason, so today's board is pure stats + scarcity.
- **`ranking_metric(p)`** (ranking.py) = `adjusted` if set else `base`. **Everything** — VORP,
  ranks, tiers — reads this one function, so the views can't disagree.
- **VORP** = `ranking_metric − positional replacement` (greedy lineup-fill,
  `config.compute_replacement_levels`) → `overall_rank` (value-based drafting). **Tiers** = gaps
  within position. **ADP** is comparison-only: `value_vs_adp = adp_rank − overall_rank`, set only
  for `overall_rank ≤ 200` (else null) — never an input to ranking.

## Modules (`pipeline/src/ffrank/`)

`config` (league/scoring/replacement rule) · `schema` (pydantic ↔ contract) · `probe` (runtime
nflreadpy column probe) · `ingest` (nflreadpy → `PlayerHistory`, vets + rookies) · `scoring`
(component stats × `ScoringConfig` → points; matches nflverse `fantasy_points_ppr`) · `project`
(`base_points` engine) · `ranking` (VORP/ranks/tiers) · `adp` (FFC → market block) · `vegas`
(Odds API totals + `finalize_adjusted`) · `softsignals` ($0 LLM workflow) · `validate` (gate) ·
`rank` (the `build_contract` orchestrator + CLI — the entry point).

## Data sources & files

- **Stats:** `nflreadpy` (NOT `nfl-data-py`, which is abandoned). Uses Polars. **Verify column
  names with `probe.py` before coding** — they're not all documented.
- **ADP:** FantasyFootballCalculator free API (Sleeper has **no public ADP endpoint**). Joined to
  players by normalized name + position.
- **Vegas:** The Odds API; reads `THE_ODDS_API_KEY` from env, skips gracefully if unset/offseason.
- **Committed** (`pipeline/data/`): `team_situations.json` + `soft_scores.json` are **user-generated
  via the Claude copy-paste workflow**; `*.sample.json` show the shapes.
- **Gitignored:** `pipeline/.venv`, `output/*.json`, `output/prompts/`, `reports/`,
  `app/node_modules`, `app/.next`.

## Validation gate (do not skip when touching the engine)

`make gate` predicts 2025 from ≤2024 and 2024 from ≤2023 vs actual `fantasy_points_ppr`. Bar:
**beat the naive last-season baseline on Spearman** (currently 8/8, ρ ≈ 0.63–0.78). Re-run it
after any change to `project.py` / `ranking.py` / `config.py`.

## Conventions

- Match the surrounding code's style. Most tests are offline; `scoring`/gate tests hit nflverse
  (cached). 38 tests currently pass.
- Verify external library/API shapes before writing against them (that's what `probe.py` is for).
- **Workflow:** do **not** push to GitHub without explicit approval; check in at major feature
  boundaries. Keep `app/` uncommitted until Part B is actually built.

## Status

Part A is **feature-complete**: ingestion, scoring, projection, VORP/tiers, ADP, Vegas (targeted),
rookies, soft signals, and ppr/half/standard formats. 38 tests pass; gate PASS. **Part B (the
Next.js app) is not built.**

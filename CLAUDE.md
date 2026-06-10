# CLAUDE.md

Guidance for working in this repo. Keep it accurate — update it when the architecture changes.

## Project

Pre-draft **fantasy football ranking tool**, skill positions only (QB/RB/WR/TE — no DST/kickers).
Produces four views over **one number per player (projected fantasy points)**: overall ranks,
positional tiers, projected points, and value-vs-ADP. Build one projection engine; derive the
four views from it — do not build four separate features.

Locked decisions: **12-team, 1QB/2RB/2WR/1TE/1FLEX**, **Full PPR** default (half/standard also
supported). **Cost target $0** (no paid APIs; situational judgment is entered as manual 1-5 ratings).

## Architecture — two parts, one JSON contract

The contract is `schema/contract.schema.json`. Lock it first; both parts hang off it.

- **Part A — `pipeline/`** (Python, offline): nflverse data → projected points → JSON. The
  pipeline is **offline/committed**, never run on a server (Vercel only serves the static JSON).
- **Part B — `app/`** (Next.js App Router + Tailwind, "Draft Room"): renders the JSON. Built.
  Mobile-first dark mossy-green UI; three views (Overall / By Position / Values) + a player
  detail drawer. Reads `app/data/rankings.json` (a top-300 trim of a pipeline run, committed).
  `cd app && npm run dev` (port 3000) / `npm run build` (static, Vercel-ready). Design tokens in
  `app/tailwind.config.ts`; contract types in `app/lib/types.ts`; helpers in `app/lib/format.ts`.

## Running Part A

Requires **Python 3.12** (system `python3` is 3.9 — too old for `nflreadpy`, which needs ≥3.10).
The venv lives at `pipeline/.venv`. Run everything from `pipeline/` via the Makefile:

```
make board [SEASON=2026] [SCORING=ppr|half|standard]   # build + print board, write JSON
make gate            # retro-validation gate
make test            # pytest
make probe [SEASON=2024]   # print LIVE nflreadpy schemas (verify columns before coding)
```

`make board` automatically applies the committed soft ratings (`data/team_situations.json` +
`data/player_overrides.json`); pass `--no-soft` to `ffrank.rank` to rank on `base_points` only.

Modules run with `PYTHONPATH=src` (the Makefile sets it). **`pip install -e .` is flaky here**
(setuptools strict-editable doesn't register on this machine) — prefer `PYTHONPATH=src`. Tests
get `src/` via `pyproject.toml`'s `pythonpath`, so `make test` needs no env.

## Ranking model — how the signals combine (keep them non-overlapping)

- **`base_points`** = stats (veterans) or draft capital (rookies, scaled per scoring format).
  The veteran engine (`project.py`): recency+reliability-weighted per-game blend of **TD-regressed**
  points (career TD spikes pulled toward yardage-expected, `TD_PER_YARD`) → × **expected games**
  (`expected_games`: own games history regressed toward 17 + small age tax, so fragile players
  don't over-project) → age curve. Both levers were validated on the gate (mean Spearman
  0.714→0.751, top-24 0.65→0.71); trajectory-recency and opportunity-trend were tried and
  **rejected** (they hurt) — see `experiments.py`. The foundation.
- **`adjusted_points = base × vegas_mult × soft_mult`** — computed in **one place**,
  `vegas.finalize_adjusted`:
  - **Vegas tilt** (±8%, clamped) applies **only to rookies + team-changers**
    (`vegas.new_env_player_ids` — players whose current environment isn't in their stats).
    Stay-put veterans are untouched, so Vegas never double-counts offense already in their points.
  - **`soft_score`** (clamped ±15%) = **manual 1-5 ratings** of six non-overlapping situational
    factors. Team-wide (`team_situations.json`): QB, OL, scheme/coaching, pace. Player-level
    (`player_overrides.json`): role/opportunity, target/touch competition. Each rating's deviation
    from 3 (neutral) is weighted by a **position-specific table summing to 0.15** (`FACTOR_WEIGHTS`
    in `softsignals.py`) — e.g. OL drives RBs, QB drives WR/TE, and is zeroed where it doesn't
    apply. Ratings are entered in the app's Soft Signals studio, downloaded as the two JSON files.
    **Ratings are CHANGE vs last year, not absolute level (3 = unchanged → no effect):**
    `base_points` already encodes a returning vet's role/offense/QB/competition (it *is* their
    production), so rating those levels would double-count. Only what's *different* — new QB,
    scheme, OL, role, or competition; and a rookie's whole new landing spot — is rated. Same
    anti-double-counting logic as the Vegas targeting (stay-put vets stay near neutral).
  - If neither applies, `adjusted` stays null → the board ranks on `base_points` (signals-off
    fallback). Vegas is null in the deep offseason, so an unrated board is pure stats + scarcity.
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
(Odds API totals + `finalize_adjusted`) · `softsignals` (manual 1-5 ratings → `soft_score`;
`FACTOR_WEIGHTS` + `compute_soft_scores`) · `validate` (gate) ·
`rank` (the `build_contract` orchestrator + CLI — the entry point).

## Data sources & files

- **Stats:** `nflreadpy` (NOT `nfl-data-py`, which is abandoned). Uses Polars. **Verify column
  names with `probe.py` before coding** — they're not all documented.
- **ADP:** FantasyFootballCalculator free API (Sleeper has **no public ADP endpoint**). Joined to
  players by normalized name + position.
- **Vegas:** The Odds API; reads `THE_ODDS_API_KEY` from env, skips gracefully if unset/offseason.
- **Committed** (`pipeline/data/`): `team_situations.json` + `player_overrides.json` are
  **user-generated via the app's Soft Signals studio** (manual 1-5 ratings, then Download);
  `*.sample.json` show the shapes.
- **Gitignored:** `pipeline/.venv`, `output/*.json`, `output/prompts/`, `reports/`,
  `app/node_modules`, `app/.next`.

## Validation gate (do not skip when touching the engine)

`make gate` predicts 2025 from ≤2024 and 2024 from ≤2023 vs actual `fantasy_points_ppr`. Bar:
**beat the naive last-season baseline on Spearman** (currently 8/8, ρ ≈ 0.70–0.81). Re-run it
after any change to `project.py` / `ranking.py` / `config.py`. To A/B a new projection lever
across all 8 folds before promoting it, use the experiment harness:
`PYTHONPATH=src python -m ffrank.experiments`.

## Conventions

- Match the surrounding code's style. Most tests are offline; `scoring`/gate tests hit nflverse
  (cached). 38 tests currently pass.
- Verify external library/API shapes before writing against them (that's what `probe.py` is for).
- **Workflow:** do **not** push to GitHub without explicit approval; check in at major feature
  boundaries. Keep `app/` uncommitted until Part B is actually built.

## Status

**Both parts complete.** Part A (Python pipeline): ingestion, scoring, projection, VORP/tiers, ADP,
Vegas (targeted), rookies, soft signals (manual 1-5 ratings), ppr/half/standard. 43 tests pass;
gate PASS. Part B
(Next.js "Draft Room" app): three views + detail drawer, mobile-first mossy-green UI, production
build verified.

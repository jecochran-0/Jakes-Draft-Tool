"""Projection experiment harness — measure candidate base_points improvements on the gate folds.

Scores arbitrary projector callables (PlayerHistory -> points) across the same 8 retro folds the
validation gate uses (predict 2025 from <=2024 and 2024 from <=2023, four positions), reporting
mean Spearman + top-24 hit vs the naive last-season baseline. This is the empirical decider: a
candidate ships only if it beats the current engine here.

Run:  PYTHONPATH=src python -m ffrank.experiments
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

import polars as pl
from scipy import stats as sps

from .config import DEFAULT_SCORING, SEASON_GAMES
from .ingest import build_histories, stats_table
from .project import (POSITION_BASELINE_PG, RECENCY_WEIGHTS, SHRINK_TO_BASELINE,
                      age_multiplier, project_base_points)

SEASONS = [2025, 2024]
POSITIONS = ["RB", "WR", "TE", "QB"]
TD_VALUE = {"pass": 4.0, "rush": 6.0, "rec": 6.0}  # matches ScoringConfig defaults


# ----- fold data ------------------------------------------------------------------------

@dataclass
class Fold:
    season: int
    position: str
    histories: list           # PlayerHistory with an actual that season
    actual: dict              # gsis_id -> actual points
    league_td_rate: dict      # {"pass"/"rush"/"rec": td_per_yard} from the training window


def _league_td_rates(histories) -> dict:
    tot = {"pass_td": 0.0, "pass_yds": 0.0, "rush_td": 0.0, "rush_yds": 0.0,
           "rec_td": 0.0, "rec_yds": 0.0}
    for h in histories:
        for s in h.seasons:
            tot["pass_td"] += s.pass_td; tot["pass_yds"] += s.pass_yds
            tot["rush_td"] += s.rush_td; tot["rush_yds"] += s.rush_yds
            tot["rec_td"] += s.rec_td; tot["rec_yds"] += s.rec_yds
    rate = lambda td, yd: (td / yd) if yd > 0 else 0.0
    return {"pass": rate(tot["pass_td"], tot["pass_yds"]),
            "rush": rate(tot["rush_td"], tot["rush_yds"]),
            "rec": rate(tot["rec_td"], tot["rec_yds"])}


def load_folds() -> list[Fold]:
    folds: list[Fold] = []
    for season in SEASONS:
        for pos in POSITIONS:
            histories = build_histories(season, DEFAULT_SCORING, position=pos)
            actual = {r["player_id"]: r["points"]
                      for r in stats_table((season,), DEFAULT_SCORING)
                      .filter(pl.col("position") == pos).to_dicts()}
            scorable = [h for h in histories if actual.get(h.gsis_id) is not None]
            folds.append(Fold(season, pos, scorable, actual, _league_td_rates(histories)))
    return folds


def naive(h) -> float:
    if not h.seasons:
        return 0.0
    last = max(h.seasons, key=lambda s: s.season)
    return last.points / last.games * SEASON_GAMES if last.games else 0.0


# ----- configurable projector (the thing we vary) ---------------------------------------

def _recency_weights(n: int, weights) -> list[float]:
    w = weights[:n]
    s = sum(w) or 1.0
    return [x / s for x in w]


def _td_regressed_points(s, rates: dict, lam: float) -> float:
    """A season's points with each category's TDs pulled `lam` toward yardage-expected TDs."""
    exp = {"pass": s.pass_yds * rates["pass"], "rush": s.rush_yds * rates["rush"],
           "rec": s.rec_yds * rates["rec"]}
    act = {"pass": s.pass_td, "rush": s.rush_td, "rec": s.rec_td}
    delta = sum(TD_VALUE[k] * (lam * exp[k] + (1 - lam) * act[k] - act[k]) for k in exp)
    return s.points + delta


def project(h, fold: Fold, *, recency="fixed", td_lambda=0.0, opp_beta=0.0,
            avail=False) -> float:
    """Configurable veteran projector. Defaults reproduce the production engine exactly."""
    lines = sorted(h.seasons, key=lambda s: s.season, reverse=True)[:3]
    lines = [ln for ln in lines if ln.games and ln.games > 0]
    baseline_pg = POSITION_BASELINE_PG.get(h.position, 7.0)
    age_mult = age_multiplier(h.position, h.age)
    if not lines:
        return baseline_pg * SEASON_GAMES * age_mult

    # recency scheme
    if recency == "trajectory":
        young = (h.age is not None and h.age <= {"RB": 24, "WR": 24, "TE": 25, "QB": 25}.get(h.position, 24))
        weights = [0.85, 0.12, 0.03] if young else [0.6, 0.25, 0.15]
    else:
        weights = RECENCY_WEIGHTS
    recency_w = _recency_weights(len(lines), weights)

    rel = [w * min(ln.games, SEASON_GAMES) / SEASON_GAMES for w, ln in zip(recency_w, lines)]
    total_w = sum(rel) or 1.0

    def season_pg(ln):
        pts = _td_regressed_points(ln, fold.league_td_rate, td_lambda) if td_lambda > 0 else ln.points
        return pts / ln.games

    blended_pg = sum(w * season_pg(ln) for w, ln in zip(rel, lines)) / total_w
    calibrated_pg = (1 - SHRINK_TO_BASELINE) * blended_pg + SHRINK_TO_BASELINE * baseline_pg

    # opportunity: nudge by last-season role trend vs the prior season
    if opp_beta > 0 and len(lines) >= 2:
        share = (lambda s: s.target_share if h.position in ("WR", "TE") else s.snap_share)
        cur, prev = share(lines[0]), share(lines[1])
        if cur is not None and prev is not None:
            calibrated_pg *= max(0.9, min(1.1, 1.0 + opp_beta * (cur - prev)))

    games = SEASON_GAMES
    if avail:
        games = expected_games(h)
    return calibrated_pg * games * age_mult


def expected_games(h) -> float:
    """Expected games played: recency-weighted games history, blended toward 17, age-taxed."""
    lines = sorted(h.seasons, key=lambda s: s.season, reverse=True)[:3]
    lines = [ln for ln in lines if ln.games]
    if not lines:
        return SEASON_GAMES
    w = _recency_weights(len(lines), [0.6, 0.3, 0.1])
    g = sum(wi * min(ln.games, SEASON_GAMES) for wi, ln in zip(w, lines))
    # blend the player's own history (60%) toward a full season (40%) — durability persists but regresses
    exp = 0.6 * g + 0.4 * SEASON_GAMES
    if h.age is not None:
        if h.position == "RB" and h.age >= 28:
            exp -= 0.8
        if h.age >= 31:
            exp -= 0.8
    return max(8.0, min(SEASON_GAMES, exp))


# ----- scoring --------------------------------------------------------------------------

def _metrics(pred: list[float], actual: list[float], top_n: int = 24):
    rho = float(sps.spearmanr(pred, actual).statistic)
    idx = sorted(range(len(actual)), key=lambda i: actual[i], reverse=True)[:top_n]
    pidx = sorted(range(len(pred)), key=lambda i: pred[i], reverse=True)[:top_n]
    hit = len(set(idx) & set(pidx)) / min(top_n, len(actual))
    return rho, hit


def score(projector, folds: list[Fold]):
    rows = []
    for f in folds:
        actual = [f.actual[h.gsis_id] for h in f.histories]
        pred = [projector(h, f) for h in f.histories]
        nav = [naive(h) for h in f.histories]
        rho, hit = _metrics(pred, actual)
        nrho, nhit = _metrics(nav, actual)
        rows.append((f, rho, hit, nrho, nhit))
    return rows


def _summarize(name, rows):
    rho = mean(r[1] for r in rows)
    hit = mean(r[2] for r in rows)
    beats = sum(1 for r in rows if r[1] > r[3])
    print(f"{name:28s} meanRho={rho:.4f}  meanTop24={hit:.3f}  beats-naive {beats}/8")
    return rho, hit


def main():
    print("Loading folds (nflverse, cached)…")
    folds = load_folds()

    nrho = mean(float(sps.spearmanr([naive(h) for h in f.histories],
                                    [f.actual[h.gsis_id] for h in f.histories]).statistic) for f in folds)
    print(f"naive baseline             meanRho={nrho:.4f}\n")

    # `project(...)` with all flags OFF reproduces the LEGACY pre-improvement engine; the flags are
    # the levers tested. `project_base_points` is the CURRENT production engine (TD-regress +
    # availability already promoted). Rejected levers kept for the record (they hurt).
    variants = {
        "legacy (pre-improvement)": lambda h, f: project(h, f),
        "+ trajectory recency":     lambda h, f: project(h, f, recency="trajectory"),
        "+ opportunity beta=2":     lambda h, f: project(h, f, opp_beta=2.0),
        "+ td-regress 0.7":         lambda h, f: project(h, f, td_lambda=0.7),
        "+ availability":           lambda h, f: project(h, f, avail=True),
        "+ td0.7 + avail":          lambda h, f: project(h, f, td_lambda=0.7, avail=True),
        "PRODUCTION (promoted)":    lambda h, f: project_base_points(h),
    }
    for name, proj in variants.items():
        _summarize(name, score(proj, folds))

    print("\nPer-position Spearman (rows = variant, vs legacy):")
    base_rows = score(variants["legacy (pre-improvement)"], folds)
    base_by = {(r[0].season, r[0].position): r[1] for r in base_rows}
    for name, proj in variants.items():
        rows = score(proj, folds)
        deltas = " ".join(
            f"{r[0].position}{str(r[0].season)[2:]}{(r[1]-base_by[(r[0].season,r[0].position)]):+.3f}"
            for r in rows)
        print(f"  {name:24s} {deltas}")


if __name__ == "__main__":
    main()

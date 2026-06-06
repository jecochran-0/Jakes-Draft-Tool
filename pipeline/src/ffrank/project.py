"""base_points projection engine (§6a).

Operates on a clean PlayerHistory dataclass so it is testable independent of nflreadpy
ingestion. Two branches:

  Veterans — recency-weighted blend of per-game fantasy rates over the last up-to-3
  seasons, normalized to a full 17-game season, regressed toward a position+age baseline
  (shrinks thin/volatile samples), then scaled by a conservative age multiplier.

  Rookies — no prior-season production, so base_points comes from draft capital +
  depth-chart opportunity (landing spot). Tagged is_rookie=True. Excluded from the
  validation gate (no retro history to score against).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import SEASON_GAMES

# Recency weights, newest -> oldest, for up to 3 seasons. Renormalized when fewer exist.
# Tuned on 2024+2025 retro folds: 0.7/0.2/0.1 + reliability weighting beats the naive
# last-season baseline on Spearman in all 8 position-folds (validate.py is the gate).
RECENCY_WEIGHTS = [0.7, 0.2, 0.1]

# Fixed-fraction shrink of the blended per-game rate toward the position baseline. This is
# for point-value sanity on thin/extreme samples ONLY. Because it shifts every player by
# the same monotonic transform toward a per-position constant, it is RANK-PRESERVING within
# a position — it costs zero Spearman. (The previous games-based regression was NOT rank-
# preserving: it over-shrank low-games breakouts and demoted them, hurting the ranking.)
SHRINK_TO_BASELINE = 0.08

# Position baselines: replacement-ish PPR points PER GAME. Thin samples regress here.
# Derived from typical low-end-starter per-game output (documented, conservative).
POSITION_BASELINE_PG: dict[str, float] = {
    "QB": 14.0,
    "RB": 7.0,
    "WR": 7.5,
    "TE": 5.0,
}

# Rough rookie base_points by draft capital bucket (overall pick), PPR full season.
# A landing-spot opportunity factor scales these. Conservative anchors, not predictions.
ROOKIE_DRAFT_CAPITAL: list[tuple[int, float]] = [
    (10, 180.0),   # top-10 pick
    (32, 150.0),   # rest of round 1
    (64, 110.0),   # round 2
    (100, 80.0),   # round 3
    (256, 55.0),   # day 3
]


@dataclass
class SeasonLine:
    season: int
    points: float       # fantasy points in the chosen scoring, that season
    games: int


@dataclass
class PlayerHistory:
    player_id: str                 # contract id, e.g. "sleeper_4046" (falls back to gsis)
    name: str
    position: str
    age: float | None              # age during the projected season
    gsis_id: str | None = None     # raw nflverse id, for joining actuals in validation
    team: str = ""                 # latest team (enriched further by the ADP/roster slice)
    is_rookie: bool = False
    # Most-recent-season context — output enrichment for raw_stats, NOT projection inputs.
    last_snap_share: float | None = None
    last_target_share: float | None = None
    seasons: list[SeasonLine] = field(default_factory=list)  # any order; sorted internally
    # Rookie-only inputs (ignored for veterans):
    draft_pick: int | None = None
    opportunity_factor: float = 1.0  # 1.0 neutral; >1 vacated volume, <1 crowded depth chart


def age_multiplier(position: str, age: float | None) -> float:
    """Conservative position-specific age curve. 1.0 at peak; gentle decline at the edges.

    Kept deliberately mild — age is a modifier on a stats foundation, not a driver.
    """
    if age is None:
        return 1.0
    if position == "RB":
        if age <= 25:
            return 1.0
        if age <= 27:
            return 0.97
        if age <= 29:
            return 0.92
        return 0.85
    if position == "WR":
        if age <= 23:
            return 0.98          # young WRs still ascending
        if age <= 28:
            return 1.0
        if age <= 31:
            return 0.95
        return 0.88
    if position == "TE":
        if age <= 24:
            return 0.95
        if age <= 30:
            return 1.0
        return 0.93
    if position == "QB":
        if age <= 24:
            return 0.97
        if age <= 34:
            return 1.0
        return 0.95
    return 1.0


def _recency_weights(n: int) -> list[float]:
    w = RECENCY_WEIGHTS[:n]
    s = sum(w)
    return [x / s for x in w]


def project_veteran(p: PlayerHistory, games_target: int = SEASON_GAMES) -> float:
    """Reliability+recency-weighted per-game blend -> calibrate -> full season -> age adjust.

    Each season's weight = recency_weight x (min(games,17)/17), so partial seasons (small
    samples) contribute less to the per-game rate than full ones. We do NOT shrink by total
    games observed (that distorted ranks by demoting low-games breakouts); calibration is a
    fixed, rank-preserving nudge toward the position baseline.
    """
    # Most recent up to 3 seasons, newest first.
    lines = sorted(p.seasons, key=lambda s: s.season, reverse=True)[:3]
    lines = [ln for ln in lines if ln.games and ln.games > 0]
    baseline_pg = POSITION_BASELINE_PG.get(p.position, 7.0)
    if not lines:
        return baseline_pg * games_target * age_multiplier(p.position, p.age)

    recency = _recency_weights(len(lines))
    weights = [w * min(ln.games, games_target) / games_target for w, ln in zip(recency, lines)]
    total_w = sum(weights) or 1.0
    blended_pg = sum(w * (ln.points / ln.games) for w, ln in zip(weights, lines)) / total_w

    calibrated_pg = (1 - SHRINK_TO_BASELINE) * blended_pg + SHRINK_TO_BASELINE * baseline_pg
    return calibrated_pg * games_target * age_multiplier(p.position, p.age)


def project_rookie(p: PlayerHistory, games_target: int = SEASON_GAMES) -> float:
    """Draft-capital prior scaled by landing-spot opportunity. (Vegas added later slice.)"""
    pick = p.draft_pick if p.draft_pick is not None else 256
    base = ROOKIE_DRAFT_CAPITAL[-1][1]
    for threshold, value in ROOKIE_DRAFT_CAPITAL:
        if pick <= threshold:
            base = value
            break
    return base * p.opportunity_factor


def project_base_points(p: PlayerHistory, games_target: int = SEASON_GAMES) -> float:
    """Dispatch: rookies use the draft-capital branch, everyone else the stat blend."""
    if p.is_rookie or not p.seasons:
        return project_rookie(p, games_target)
    return project_veteran(p, games_target)

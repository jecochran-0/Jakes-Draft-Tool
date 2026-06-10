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

# --- Touchdown regression (validated on the gate: +~0.012 Spearman, biggest for QB) ----------
# Touchdowns are the highest-variance fantasy input and regress hard year-to-year. We pull each
# season's TDs `TD_REGRESS_LAMBDA` of the way toward a yardage-expected count before blending, so
# career TD spikes don't carry forward at full weight. Rates are league TD-per-yard by position +
# category, derived from 2024-2025 nflverse aggregates (stable league constants; the irrelevant
# cells — e.g. RB passing — sit at ~0 yards so they contribute nothing). TD point values are
# scoring-format-invariant, so this is identical across ppr/half/standard.
TD_REGRESS_LAMBDA = 0.7
TD_POINTS = {"pass": 4.0, "rush": 6.0, "rec": 6.0}
TD_PER_YARD: dict[str, dict[str, float]] = {
    "QB": {"pass": 0.0060, "rush": 0.0105, "rec": 0.0},
    "RB": {"pass": 0.0,    "rush": 0.0070, "rec": 0.0051},
    "WR": {"pass": 0.0,    "rush": 0.0082, "rec": 0.0059},
    "TE": {"pass": 0.0,    "rush": 0.0148, "rec": 0.0069},
}

# --- Expected games / availability (validated on the gate: +~0.033 Spearman, the biggest lever) --
# The old engine projected EVERYONE to a full 17 games, so a fragile high-ppg player looked
# identical to an iron-man. We instead expect games from the player's own recency-weighted games
# history, regressed 40% toward a full season (durability persists but isn't destiny), with a
# small age tax. This de-risks injury-prone players — exactly the draft trap a per-game model hides.
EXP_GAMES_RECENCY = [0.6, 0.3, 0.1]
EXP_GAMES_SELF_WEIGHT = 0.6   # 60% own history, 40% full-season regression
EXP_GAMES_FLOOR = 8.0

# Rookie base_points anchors by POSITION and draft-capital bucket (overall pick), full-season
# PPR. Position-specific because year-1 fantasy value differs sharply: rookie RB/WR can be
# immediately productive, rookie QBs score on a higher absolute scale (so a flat RB/WR anchor
# would make startable rookie QBs look undraftable), and rookie TEs almost never produce.
# These are conservative anchors, not predictions; a landing-spot opportunity_factor scales
# them, and the deferred soft-signals/Vegas slices refine further.
ROOKIE_BASE_BY_POS: dict[str, list[tuple[int, float]]] = {
    "RB": [(10, 190.0), (32, 150.0), (64, 110.0), (100, 75.0), (256, 45.0)],
    "WR": [(10, 175.0), (32, 140.0), (64, 100.0), (100, 70.0), (256, 40.0)],
    "TE": [(10, 110.0), (32, 80.0), (64, 55.0), (100, 40.0), (256, 25.0)],
    "QB": [(10, 250.0), (32, 210.0), (64, 150.0), (100, 90.0), (256, 50.0)],
}
_ROOKIE_FALLBACK = [(10, 175.0), (32, 140.0), (64, 100.0), (100, 70.0), (256, 40.0)]

# Rookie anchors above are PPR. Veteran points scale with format (receptions), but the anchors
# don't — so in half/standard rookies would float up relative to a compressed veteran field.
# These factors (derived empirically from the median of the top-36 veterans per position in
# each format vs PPR) scale the anchors so rookies track the same compression. QB ~ unchanged
# (no receptions); WR loses the most without PPR.
ROOKIE_FORMAT_SCALE: dict[str, dict[str, float]] = {
    "ppr":      {"QB": 1.0, "RB": 1.00, "WR": 1.00, "TE": 1.00},
    "half":     {"QB": 1.0, "RB": 0.92, "WR": 0.84, "TE": 0.83},
    "standard": {"QB": 1.0, "RB": 0.83, "WR": 0.67, "TE": 0.63},
}


@dataclass
class SeasonLine:
    season: int
    points: float       # fantasy points in the chosen scoring, that season
    games: int
    # Optional per-season components (default 0/None → callers that don't populate them keep
    # the legacy points-only behavior). Used by the efficiency-regression / opportunity experiments.
    pass_yds: float = 0.0
    pass_td: float = 0.0
    rush_yds: float = 0.0
    rush_td: float = 0.0
    receptions: float = 0.0
    rec_yds: float = 0.0
    rec_td: float = 0.0
    target_share: float | None = None
    snap_share: float | None = None


@dataclass
class PlayerHistory:
    player_id: str                 # contract id, e.g. "sleeper_4046" (falls back to gsis)
    name: str
    position: str
    age: float | None              # age during the projected season
    gsis_id: str | None = None     # raw nflverse id, for joining actuals in validation
    team: str = ""                 # latest team (current roster)
    last_stats_team: str | None = None  # team of the most-recent stat season (team-change detection)
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


def _recency_weights(n: int, weights: list[float] = RECENCY_WEIGHTS) -> list[float]:
    w = weights[:n]
    s = sum(w) or 1.0
    return [x / s for x in w]


def _regressed_points(s: "SeasonLine", position: str) -> float:
    """A season's fantasy points with each TD category pulled TD_REGRESS_LAMBDA toward its
    yardage-expected count. Categories with no yards (or zero rate) are untouched."""
    rates = TD_PER_YARD.get(position)
    if not rates:
        return s.points
    delta = (
        TD_POINTS["pass"] * (s.pass_yds * rates["pass"] - s.pass_td)
        + TD_POINTS["rush"] * (s.rush_yds * rates["rush"] - s.rush_td)
        + TD_POINTS["rec"] * (s.rec_yds * rates["rec"] - s.rec_td)
    )
    return s.points + TD_REGRESS_LAMBDA * delta


def expected_games(p: PlayerHistory) -> float:
    """Expected games played next season: recency-weighted games history regressed toward a full
    season, with a small age tax. Replaces the old flat 17 so fragile players don't over-project."""
    lines = [ln for ln in sorted(p.seasons, key=lambda s: s.season, reverse=True)[:3] if ln.games]
    if not lines:
        return SEASON_GAMES
    w = _recency_weights(len(lines), EXP_GAMES_RECENCY)
    own = sum(wi * min(ln.games, SEASON_GAMES) for wi, ln in zip(w, lines))
    exp = EXP_GAMES_SELF_WEIGHT * own + (1 - EXP_GAMES_SELF_WEIGHT) * SEASON_GAMES
    if p.position == "RB" and p.age is not None and p.age >= 28:
        exp -= 0.8
    if p.age is not None and p.age >= 31:
        exp -= 0.8
    return max(EXP_GAMES_FLOOR, min(SEASON_GAMES, exp))


def project_veteran(p: PlayerHistory, games_target: int = SEASON_GAMES) -> float:
    """Reliability+recency-weighted per-game blend -> calibrate -> expected games -> age adjust.

    Each season's weight = recency_weight x (min(games,17)/17), so partial seasons (small
    samples) contribute less to the per-game rate than full ones. The per-game rate uses
    TD-regressed points (career TD spikes don't carry forward at full weight). The full-season
    multiply uses EXPECTED games (availability), not a flat 17, so fragile players don't
    over-project. Calibration is a fixed, rank-preserving nudge toward the position baseline.
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
    blended_pg = sum(w * (_regressed_points(ln, p.position) / ln.games)
                     for w, ln in zip(weights, lines)) / total_w

    calibrated_pg = (1 - SHRINK_TO_BASELINE) * blended_pg + SHRINK_TO_BASELINE * baseline_pg
    games = expected_games(p) if games_target == SEASON_GAMES else games_target
    return calibrated_pg * games * age_multiplier(p.position, p.age)


def project_rookie(p: PlayerHistory, scoring_key: str = "ppr",
                   games_target: int = SEASON_GAMES) -> float:
    """Position-aware draft-capital prior, scaled to the scoring format and landing-spot
    opportunity. (The Vegas landing-spot tilt is applied downstream in finalize_adjusted.)"""
    pick = p.draft_pick if p.draft_pick is not None else 256
    anchors = ROOKIE_BASE_BY_POS.get(p.position, _ROOKIE_FALLBACK)
    base = anchors[-1][1]
    for threshold, value in anchors:
        if pick <= threshold:
            base = value
            break
    fmt = ROOKIE_FORMAT_SCALE.get(scoring_key, ROOKIE_FORMAT_SCALE["ppr"])
    return base * fmt.get(p.position, 1.0) * p.opportunity_factor


def project_base_points(p: PlayerHistory, scoring_key: str = "ppr",
                        games_target: int = SEASON_GAMES) -> float:
    """Dispatch: rookies use the draft-capital branch, everyone else the stat blend."""
    if p.is_rookie or not p.seasons:
        return project_rookie(p, scoring_key, games_target)
    return project_veteran(p, games_target)

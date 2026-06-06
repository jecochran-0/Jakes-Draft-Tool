"""Project-level config + the replacement-level rule that keys VORP (§6c).

Locked decisions (this session):
  - League: 12-team, 1QB / 2RB / 2WR / 1TE / 1FLEX (flex = RB/WR/TE).
  - Scoring: Full PPR.

Replacement level is DERIVED, not a magic number: we greedily fill every team's
starting lineup from a points-ranked pool (FLEX goes to the best remaining flex-eligible
player), and the first *undrafted* player at each position defines that position's
replacement level. For the 12-team standard lineup this lands ~QB13, TE13, and RB/WR in
the low-30s/upper-30s depending on how the flex splits — see compute_replacement_levels.
"""
from __future__ import annotations

from .schema import LeagueConfig, ScoringConfig

# Season context. Today is 2026 → 2025 is the most recent completed season.
CURRENT_SEASON = 2026
LAST_COMPLETED_SEASON = 2025

# 17-game modern NFL regular season.
SEASON_GAMES = 17

DEFAULT_SCORING = ScoringConfig()          # Full PPR defaults
DEFAULT_LEAGUE = LeagueConfig()            # 12-team standard

# Scoring presets — the spec's three formats. Different format = re-run = its own output file.
# Only the per-reception value changes; everything else (yardage, TDs, etc.) is shared.
# Note: ranking is unaffected by the baseline shrink (a rank-preserving per-position constant);
# changing format re-scores points and so re-orders the board on real scoring differences.
SCORING_CONFIGS: dict[str, ScoringConfig] = {
    "ppr": ScoringConfig(ppr=1.0, rec=1.0),
    "half": ScoringConfig(ppr=0.5, rec=0.5),
    "standard": ScoringConfig(ppr=0.0, rec=0.0),
}


def scoring_for(key: str) -> ScoringConfig:
    if key not in SCORING_CONFIGS:
        raise ValueError(f"unknown scoring '{key}'; choose from {sorted(SCORING_CONFIGS)}")
    return SCORING_CONFIGS[key]


def base_lineup_slots(league: LeagueConfig) -> dict[str, int]:
    """Non-flex starting slots per position, league-wide (teams * per-team)."""
    return {
        pos: count * league.teams
        for pos, count in league.lineup.items()
        if pos != "FLEX"
    }


def compute_replacement_levels(
    points_by_pos: dict[str, list[float]],
    league: LeagueConfig = DEFAULT_LEAGUE,
) -> dict[str, float]:
    """Greedy lineup-fill → replacement points per position.

    points_by_pos: {position: [player_points...]} (any order; sorted here).
    Returns the *points* of the first undrafted player at each position. If a position
    runs out of players before its starters are filled, replacement is 0.0 for it.
    """
    pools = {pos: sorted(pts, reverse=True) for pos, pts in points_by_pos.items()}
    cursors: dict[str, int] = {pos: 0 for pos in pools}

    base = base_lineup_slots(league)
    # Fill dedicated (non-flex) starter slots first.
    for pos, n_slots in base.items():
        cursors[pos] = min(n_slots, len(pools.get(pos, [])))

    # Fill FLEX slots greedily with the best remaining flex-eligible player.
    flex_total = league.lineup.get("FLEX", 0) * league.teams
    for _ in range(flex_total):
        best_pos, best_val = None, float("-inf")
        for pos in league.flex_eligible:
            i = cursors.get(pos, 0)
            pool = pools.get(pos, [])
            if i < len(pool) and pool[i] > best_val:
                best_pos, best_val = pos, pool[i]
        if best_pos is None:
            break
        cursors[best_pos] += 1

    levels: dict[str, float] = {}
    for pos, pool in pools.items():
        i = cursors[pos]
        levels[pos] = pool[i] if i < len(pool) else 0.0
    return levels


def replacement_ranks(league: LeagueConfig = DEFAULT_LEAGUE) -> dict[str, int]:
    """The *rank index* (1-based) of replacement at each position, assuming a deep pool
    so FLEX is exhausted. Useful as a documented sanity check / fallback.

    For 12-team 1QB/2RB/2WR/1TE/1FLEX with a typical flex split (~ all RB/WR), this is
    QB13, TE13, and RB+WR base 24+24 = 48 starters plus 12 flex distributed by value.
    The exact RB/WR split depends on the projection pool, so the dynamic function above
    is authoritative; these are nominal anchors.
    """
    base = {pos: c * league.teams for pos, c in league.lineup.items() if pos != "FLEX"}
    return {pos: n + 1 for pos, n in base.items()}

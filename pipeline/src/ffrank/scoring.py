"""Fantasy point scoring from component stats, given a ScoringConfig.

Pure functions over a dict-like stat row (column name -> value). Column names are the
nflverse `load_player_stats` fields (verified at runtime by probe.py). We compute our own
points so scoring format stays configurable; we also expose the nflverse-provided
`fantasy_points_ppr` for cross-checking (see tests).
"""
from __future__ import annotations

from typing import Mapping

from .schema import ScoringConfig


def _g(row: Mapping, key: str) -> float:
    """Safe getter — missing/None stat columns count as 0."""
    v = row.get(key)
    return float(v) if v is not None else 0.0


def points(row: Mapping, scoring: ScoringConfig) -> float:
    """Fantasy points for a single player-season (or week) stat row.

    Expects nflverse component columns: passing_yards, passing_tds, passing_interceptions,
    rushing_yards, rushing_tds, receptions, receiving_yards, receiving_tds,
    rushing_fumbles_lost, receiving_fumbles_lost, sack_fumbles_lost, and 2pt conversions.
    Unknown/absent columns contribute 0, so this degrades gracefully across schema drifts.
    """
    pts = 0.0
    # Passing
    pts += _g(row, "passing_yards") * scoring.pass_yd
    pts += _g(row, "passing_tds") * scoring.pass_td
    pts += _g(row, "passing_interceptions") * scoring.pass_int
    # Rushing
    pts += _g(row, "rushing_yards") * scoring.rush_yd
    pts += _g(row, "rushing_tds") * scoring.rush_td
    # Receiving
    pts += _g(row, "receptions") * scoring.rec
    pts += _g(row, "receiving_yards") * scoring.rec_yd
    pts += _g(row, "receiving_tds") * scoring.rec_td
    # Fumbles lost (nflverse splits these across rushing/receiving/sack)
    fumbles_lost = (
        _g(row, "rushing_fumbles_lost")
        + _g(row, "receiving_fumbles_lost")
        + _g(row, "sack_fumbles_lost")
    )
    pts += fumbles_lost * scoring.fumble_lost
    # Two-point conversions
    two_pt = (
        _g(row, "passing_2pt_conversions")
        + _g(row, "rushing_2pt_conversions")
        + _g(row, "receiving_2pt_conversions")
    )
    pts += two_pt * scoring.two_pt
    return pts

"""VORP -> ranks -> tiers (spec §6c/§6d).

Turns each player's projected points into a draft board:
  - VORP (value over replacement) makes positions comparable: a 300-pt QB is worth less
    in a 1QB league than a 250-pt RB, because replacement QB is far more productive than
    replacement RB. VORP = points - replacement_level(position).
  - overall_rank is by VORP (value-based drafting), so the board reflects draft value, not
    raw points. position_rank is within-position (same order as points, since replacement
    is a per-position constant).
  - Tiers are gaps in the within-position curve: a cluster of similar players ends where the
    drop to the next player is unusually large.

This slice ranks on `base_points` (adjusted_points is the deferred soft-signals output).
The metric is taken from `adjusted_points` when present, else `base_points` — so this code
needs no change once soft signals land. `value_vs_adp` is computed by the ADP slice using
the `overall_rank` produced here.
"""
from __future__ import annotations

from statistics import pstdev

from .config import DEFAULT_LEAGUE, compute_replacement_levels
from .schema import LeagueConfig, Player

# A new tier starts when the gap to the next player exceeds this many standard deviations of
# the gaps among the draftable top of the position, subject to an absolute floor so small
# gaps never split a tier. The threshold is derived from the TOP of the pool (not all ~190
# players) — deep replacement-level gaps are ~0 and would otherwise deflate sigma and
# over-split the meaningful top of the board.
TIER_GAP_SIGMAS = 0.9
TIER_GAP_FLOOR = 12.0   # PPR points (~0.7 ppg); smaller gaps never break a tier
TIER_DEPTH = 48         # players per position used to set the threshold (covers draftable depth)


def ranking_metric(p: Player) -> float:
    """The number we rank on: adjusted_points if available (soft-signals slice), else base."""
    adj = p.projection.adjusted_points
    return adj if adj is not None else p.projection.base_points


def compute_vorp(players: list[Player], league: LeagueConfig = DEFAULT_LEAGUE) -> dict[str, float]:
    """Set p.projection.vorp for every player; return the replacement level per position."""
    points_by_pos: dict[str, list[float]] = {}
    for p in players:
        points_by_pos.setdefault(p.position, []).append(ranking_metric(p))

    replacement = compute_replacement_levels(points_by_pos, league)
    for p in players:
        p.projection.vorp = round(ranking_metric(p) - replacement.get(p.position, 0.0), 1)
    return replacement


def assign_ranks(players: list[Player]) -> None:
    """Set overall_rank (by VORP, descending) and position_rank (within position)."""
    ordered = sorted(players, key=lambda p: (p.projection.vorp if p.projection.vorp is not None
                                             else ranking_metric(p)), reverse=True)
    for i, p in enumerate(ordered, 1):
        p.projection.overall_rank = i

    by_pos: dict[str, list[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)
    for group in by_pos.values():
        group.sort(key=lambda p: ranking_metric(p), reverse=True)
        for i, p in enumerate(group, 1):
            p.projection.position_rank = i


def assign_tiers(players: list[Player]) -> None:
    """Within each position, break tiers at unusually large gaps in the ranking metric."""
    by_pos: dict[str, list[Player]] = {}
    for p in players:
        by_pos.setdefault(p.position, []).append(p)

    for group in by_pos.values():
        group.sort(key=lambda p: ranking_metric(p), reverse=True)
        if len(group) < 2:
            for p in group:
                p.projection.tier = 1
            continue

        metrics = [ranking_metric(p) for p in group]
        gaps = [metrics[i] - metrics[i + 1] for i in range(len(metrics) - 1)]
        top_gaps = gaps[:TIER_DEPTH]
        sigma = pstdev(top_gaps) if len(top_gaps) > 1 else 0.0
        threshold = max(TIER_GAP_FLOOR, TIER_GAP_SIGMAS * sigma)

        tier = 1
        group[0].projection.tier = 1
        for i in range(1, len(group)):
            if gaps[i - 1] > threshold:
                tier += 1
            group[i].projection.tier = tier


def build_board(players: list[Player], league: LeagueConfig = DEFAULT_LEAGUE) -> dict[str, float]:
    """Full pipeline: VORP -> ranks -> tiers, mutating players in place. Returns replacement levels."""
    replacement = compute_vorp(players, league)
    assign_ranks(players)
    assign_tiers(players)
    return replacement

"""Soft signals (spec §6b, §7, §8) — manual situational ratings, fully offline.

Situational judgment the stats can't see (QB, offensive line, scheme/coaching, pace, the player's
role, target/touch competition) is entered BY HAND on a 1-5 scale and turned into a per-player
`soft_score` multiplier: adjusted_points = base_points × soft_score. The board then re-ranks on
adjusted_points (ranking.ranking_metric already prefers it).

Two committed inputs under pipeline/data/ (edited in the app's Soft Signals studio, then saved):
  - team_situations.json  -> [{team, qb, ol, scheme, pace, notes}]   (team-wide factors, 1-5)
  - player_overrides.json -> [{id, role, competition}]               (player factors, 1-5)

Scale: 5 = best, 3 = neutral (no effect), 1 = worst. Each factor's deviation from 3 is weighted
by a position-specific table and summed; the result is clamped to [0.85, 1.15]. A player with all
factors neutral nets zero and is left unscored (ranks on base) — the LLM-off fallback equivalent.
"""
from __future__ import annotations

import json
from pathlib import Path

from .schema import Player, Situation

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TEAM_TABLE_PATH = DATA_DIR / "team_situations.json"
PLAYER_OVERRIDES_PATH = DATA_DIR / "player_overrides.json"

SOFT_MIN, SOFT_MAX = 0.85, 1.15
NEUTRAL = 3  # 1-5 scale; 3 = neutral / no effect.

# The six non-overlapping factors. Four are team-wide (one rating per team), two are per player.
TEAM_FACTORS = ("qb", "ol", "scheme", "pace")
PLAYER_FACTORS = ("role", "competition")
FACTORS = TEAM_FACTORS + PLAYER_FACTORS

# Human labels for the auto-generated reasoning string.
FACTOR_LABEL = {
    "qb": "QB", "ol": "OL", "scheme": "scheme", "pace": "pace",
    "role": "role", "competition": "competition",
}

# Position-specific weights — the max swing each factor can contribute. Each row SUMS TO 0.15,
# so "everything maxed" lands exactly on the ±15% bound (clamp is then only a safety net).
# Tunable: this table is the single source of truth (mirrored in app/lib/softsignals.ts).
FACTOR_WEIGHTS: dict[str, dict[str, float]] = {
    # qb is 0 for RB (their own passing doesn't matter); OL leads, role close behind.
    "RB": {"qb": 0.000, "ol": 0.050, "scheme": 0.025, "pace": 0.015, "role": 0.040, "competition": 0.020},
    # OL barely matters for a WR; QB and target competition lead.
    "WR": {"qb": 0.045, "ol": 0.000, "scheme": 0.030, "pace": 0.020, "role": 0.020, "competition": 0.035},
    "TE": {"qb": 0.040, "ol": 0.000, "scheme": 0.035, "pace": 0.020, "role": 0.035, "competition": 0.020},
    # For a QB the "qb" factor is themselves (0); competition = quality of weapons; OL = protection.
    "QB": {"qb": 0.000, "ol": 0.045, "scheme": 0.040, "pace": 0.030, "role": 0.015, "competition": 0.020},
}


def _clamp(x: float) -> float:
    return max(SOFT_MIN, min(SOFT_MAX, x))


# ----- Load the two committed rating files ----------------------------------------------

def load_team_ratings(path: Path = TEAM_TABLE_PATH) -> dict[str, dict]:
    """team abbrev -> {qb, ol, scheme, pace, notes}. Missing factors default to NEUTRAL."""
    table: dict[str, dict] = {}
    if Path(path).exists():
        for r in json.loads(Path(path).read_text()):
            team = r.get("team")
            if not team:
                continue
            row = {f: int(r.get(f, NEUTRAL)) for f in TEAM_FACTORS}
            row["notes"] = r.get("notes", "")
            table[team] = row
    return table


def load_player_overrides(path: Path = PLAYER_OVERRIDES_PATH) -> dict[str, dict]:
    """player id -> {role, competition}. Missing factors default to NEUTRAL."""
    overrides: dict[str, dict] = {}
    if Path(path).exists():
        for r in json.loads(Path(path).read_text()):
            pid = r.get("id")
            if not pid:
                continue
            overrides[pid] = {f: int(r.get(f, NEUTRAL)) for f in PLAYER_FACTORS}
    return overrides


def player_ratings(p: Player, team_ratings: dict[str, dict],
                   player_overrides: dict[str, dict]) -> dict[str, int]:
    """The six 1-5 ratings for a player: team factors from its team + its player overrides."""
    trow = team_ratings.get(p.team, {})
    orow = player_overrides.get(p.id, {})
    ratings = {f: int(trow.get(f, NEUTRAL)) for f in TEAM_FACTORS}
    ratings.update({f: int(orow.get(f, NEUTRAL)) for f in PLAYER_FACTORS})
    return ratings


# ----- The model -------------------------------------------------------------------------

def _reasoning(ratings: dict[str, int], weights: dict[str, float]) -> str:
    """One-line summary naming only the factors that actually move the score (weight > 0)."""
    lifts, drags = [], []
    for f in FACTORS:
        if ratings[f] == NEUTRAL or weights.get(f, 0.0) == 0.0:
            continue
        chip = f"{FACTOR_LABEL[f]} {ratings[f]}/5"
        (lifts if ratings[f] > NEUTRAL else drags).append(chip)
    parts = []
    if lifts:
        parts.append(", ".join(lifts) + " lift")
    if drags:
        parts.append(", ".join(drags) + " drag")
    return "; ".join(parts)


def soft_for_ratings(ratings: dict[str, int], position: str) -> float:
    """Position-weighted multiplier from the six ratings, clamped to [0.85, 1.15]."""
    weights = FACTOR_WEIGHTS.get(position, {})
    raw = sum(weights.get(f, 0.0) * (ratings[f] - NEUTRAL) / 2 for f in FACTORS)
    return round(_clamp(1.0 + raw), 4)


def compute_soft_scores(players: list[Player], team_ratings: dict[str, dict],
                        player_overrides: dict[str, dict]) -> dict[str, tuple[float, str]]:
    """id -> (soft_score, reasoning) for every player whose ratings have a NET effect.

    Players with all-neutral (or only zero-weight) ratings are omitted, so they stay unscored
    and rank on base_points — the same fallback behavior as 'no soft scores provided'."""
    scores: dict[str, tuple[float, str]] = {}
    for p in players:
        ratings = player_ratings(p, team_ratings, player_overrides)
        weights = FACTOR_WEIGHTS.get(p.position, {})
        raw = sum(weights.get(f, 0.0) * (ratings[f] - NEUTRAL) / 2 for f in FACTORS)
        if abs(raw) < 1e-9:
            continue  # no net effect -> leave on base
        scores[p.id] = (round(_clamp(1.0 + raw), 4), _reasoning(ratings, weights))
    return scores


# ----- Attach / apply --------------------------------------------------------------------

def attach_situation(players: list[Player], team_ratings: dict[str, dict],
                     player_overrides: dict[str, dict]) -> None:
    """Record each player's six ratings on situation.soft_factors (for the app/contract display).
    Players with all-neutral ratings are left untouched to keep the output clean."""
    for p in players:
        ratings = player_ratings(p, team_ratings, player_overrides)
        if all(v == NEUTRAL for v in ratings.values()):
            continue
        if p.situation is None:
            p.situation = Situation()
        p.situation.soft_factors = ratings


def apply_soft_scores(players: list[Player], scores: dict[str, tuple[float, str]]) -> int:
    """Set soft_score/reasoning for matched players. adjusted_points is computed later by
    vegas.finalize_adjusted (which composes soft × Vegas). Returns count matched."""
    n = 0
    for p in players:
        hit = scores.get(p.id)
        if hit is None:
            continue
        soft, reasoning = hit
        if p.situation is None:
            p.situation = Situation()
        p.situation.soft_score = soft
        p.situation.soft_reasoning = reasoning
        n += 1
    return n


def audit(players: list[Player], top: int = 15) -> list[Player]:
    """Biggest movers by |adjusted − base| (spec §9), for human review of outliers."""
    moved = [p for p in players if p.projection.adjusted_points is not None]
    moved.sort(key=lambda p: abs(p.projection.adjusted_points - p.projection.base_points), reverse=True)
    return moved[:top]

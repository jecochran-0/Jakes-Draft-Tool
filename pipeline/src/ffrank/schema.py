"""Pydantic models mirroring schema/contract.schema.json.

Slice 1 populates: id, name, position, team, age, is_rookie, raw_stats, projection.base_points.
Everything else (situation, adjusted_points, vorp, ranks, tier, market) is Optional and
filled by later slices — the keys are reserved in the contract now.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Position = Literal["QB", "RB", "WR", "TE"]


class ScoringConfig(BaseModel):
    """Full scoring config — superset of the spec's 3-field example. One file per format."""
    ppr: float = 1.0
    pass_yd: float = 0.04           # 1 pt / 25 yds
    pass_td: float = 4.0
    pass_int: float = -2.0
    rush_yd: float = 0.1            # 1 pt / 10 yds
    rush_td: float = 6.0
    rec: float = 1.0               # mirrors ppr; kept explicit for clarity
    rec_yd: float = 0.1
    rec_td: float = 6.0
    fumble_lost: float = -2.0
    two_pt: float = 2.0


class LeagueConfig(BaseModel):
    teams: int = 12
    lineup: dict[str, int] = Field(default_factory=lambda: {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1})
    flex_eligible: list[str] = Field(default_factory=lambda: ["RB", "WR", "TE"])


class Meta(BaseModel):
    generated_at: str
    season: int
    scoring_config: ScoringConfig
    league_config: LeagueConfig


class RawStats(BaseModel):
    last_season_points: Optional[float] = None
    games_played: Optional[int] = None
    snap_share: Optional[float] = None
    target_share: Optional[float] = None
    prior_seasons_points: list[float] = Field(default_factory=list)


class Situation(BaseModel):
    qb_tier: Optional[int] = None
    oc_change: Optional[bool] = None
    vegas_team_total: Optional[float] = None
    soft_score: Optional[float] = None
    soft_reasoning: Optional[str] = None


class Projection(BaseModel):
    base_points: float
    adjusted_points: Optional[float] = None
    vorp: Optional[float] = None
    overall_rank: Optional[int] = None
    position_rank: Optional[int] = None
    tier: Optional[int] = None


class Market(BaseModel):
    adp: Optional[float] = None
    adp_rank: Optional[int] = None
    value_vs_adp: Optional[int] = None


class Player(BaseModel):
    id: str
    name: str
    position: Position
    team: str
    age: Optional[float] = None
    is_rookie: bool = False
    raw_stats: RawStats = Field(default_factory=RawStats)
    situation: Optional[Situation] = None
    projection: Projection
    market: Optional[Market] = None


class Contract(BaseModel):
    meta: Meta
    players: list[Player]

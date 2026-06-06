"""Ingestion: nflreadpy sources -> normalized per-player histories.

Column names verified via probe.py against nflreadpy 0.1.5:
  - player_stats: player_id (gsis), player_display_name, position, recent_team, season,
    games, target_share, fantasy_points_ppr, + all scoring component columns.
  - snap_counts: weekly; pfr_player_id, offense_pct -> season-mean snap_share.
  - players: gsis_id, pfr_id, birth_date, position, latest_team, rookie_season,
    draft_pick, draft_round, status.
  - ff_playerids: gsis_id <-> sleeper_id (for the contract id).

Builds per-position-filtered PlayerHistory objects that feed project.py and validate.py.
"""
from __future__ import annotations

from functools import lru_cache

import nflreadpy as nfl
import polars as pl

from .project import PlayerHistory, SeasonLine
from .schema import ScoringConfig
from .scoring import points as score_points

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Component columns we pass to scoring.points (must exist in player_stats).
_SCORING_COLS = [
    "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions",
    "rushing_yards", "rushing_tds", "rushing_2pt_conversions",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost",
]


@lru_cache(maxsize=8)
def _player_stats(seasons: tuple[int, ...]) -> pl.DataFrame:
    df = nfl.load_player_stats(seasons=list(seasons), summary_level="reg")
    return df.filter(pl.col("position").is_in(SKILL_POSITIONS))


@lru_cache(maxsize=1)
def _players() -> pl.DataFrame:
    return nfl.load_players()


@lru_cache(maxsize=1)
def _ff_ids() -> pl.DataFrame:
    return nfl.load_ff_playerids()


@lru_cache(maxsize=8)
def _snap_shares(seasons: tuple[int, ...]) -> pl.DataFrame:
    """Season-mean offensive snap share per pfr_player_id, bridged to gsis_id."""
    snaps = nfl.load_snap_counts(seasons=list(seasons))
    season_snap = (
        snaps.filter(pl.col("game_type") == "REG")
        .group_by(["pfr_player_id", "season"])
        .agg(pl.col("offense_pct").mean().alias("snap_share"))
    )
    bridge = _players().select(["pfr_id", "gsis_id"]).rename({"pfr_id": "pfr_player_id"})
    return season_snap.join(bridge, on="pfr_player_id", how="left")


def stats_table(seasons: tuple[int, ...], scoring: ScoringConfig) -> pl.DataFrame:
    """Per player-season rows with configurable `points` + nflverse `fantasy_points_ppr`."""
    df = _player_stats(seasons)

    # Compute configurable fantasy points per row (Python loop over needed columns —
    # the table is ~2k rows/season, so this is cheap and keeps scoring.py the source of truth).
    needed = [c for c in _SCORING_COLS if c in df.columns]
    rows = df.select(["player_id", "season"] + needed).to_dicts()
    pts = [score_points(r, scoring) for r in rows]
    df = df.with_columns(pl.Series("points", pts))

    keep = ["player_id", "player_display_name", "position", "recent_team", "season",
            "games", "target_share", "points", "fantasy_points_ppr"]
    return df.select([c for c in keep if c in df.columns])


def _meta_table() -> pl.DataFrame:
    """Per-player static metadata: ids, birth year, draft, rookie season, team."""
    players = _players().select(
        ["gsis_id", "display_name", "position", "birth_date", "latest_team",
         "rookie_season", "draft_pick", "draft_round", "status"]
    )
    ff = _ff_ids().select(["gsis_id", "sleeper_id"]).filter(pl.col("gsis_id").is_not_null())
    return players.join(ff, on="gsis_id", how="left")


def _contract_id(gsis_id: str, sleeper_id) -> str:
    if sleeper_id is not None and str(sleeper_id) != "":
        return f"sleeper_{sleeper_id}"
    return f"gsis_{gsis_id}"


def _birth_year(birth_date) -> int | None:
    if birth_date is None:
        return None
    try:
        return int(str(birth_date)[:4])
    except (ValueError, TypeError):
        return None


def build_histories(
    project_season: int,
    scoring: ScoringConfig,
    history_seasons: int = 3,
    position: str | None = None,
) -> list[PlayerHistory]:
    """Assemble PlayerHistory objects for projecting `project_season`.

    Uses player-seasons strictly BEFORE project_season as history (so this doubles as the
    retro-validation builder: pass a completed season and only prior data is used).
    `position` filters to one position (RB-first workflow); None keeps all skill positions.
    """
    hist_range = tuple(range(project_season - history_seasons, project_season))
    stats = stats_table(hist_range, scoring)
    if position:
        stats = stats.filter(pl.col("position") == position)

    meta = _meta_table()
    meta_by_id = {r["gsis_id"]: r for r in meta.to_dicts()}
    snaps = _snap_shares(hist_range)
    snap_by_key = {(r["gsis_id"], r["season"]): r["snap_share"] for r in snaps.to_dicts()
                   if r["gsis_id"] is not None}

    # Group stat rows by player.
    by_player: dict[str, list[dict]] = {}
    for r in stats.to_dicts():
        by_player.setdefault(r["player_id"], []).append(r)

    histories: list[PlayerHistory] = []
    for gsis_id, rows in by_player.items():
        rows.sort(key=lambda r: r["season"])
        m = meta_by_id.get(gsis_id, {})
        last = rows[-1]
        pos = last["position"]
        birth_year = _birth_year(m.get("birth_date"))
        age = (project_season - birth_year) if birth_year else None

        seasons = [SeasonLine(season=r["season"], points=r["points"], games=int(r["games"] or 0))
                   for r in rows]

        histories.append(
            PlayerHistory(
                player_id=_contract_id(gsis_id, m.get("sleeper_id")),
                name=last["player_display_name"],
                position=pos,
                age=age,
                gsis_id=gsis_id,
                team=m.get("latest_team") or last.get("recent_team") or "",
                is_rookie=False,            # veterans only (have prior-season rows by construction)
                seasons=seasons,
                draft_pick=m.get("draft_pick"),
                last_snap_share=snap_by_key.get((gsis_id, last["season"])),
                last_target_share=last.get("target_share"),
            )
        )
    return histories

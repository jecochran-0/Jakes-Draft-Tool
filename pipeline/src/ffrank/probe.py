"""Runtime column-probe for nflreadpy sources.

The spec says VERIFY library functions/columns before writing ingest logic. nflreadpy's
docs don't publish full column lists, so we introspect the live DataFrames here and print
schemas + a couple sample rows. Run this BEFORE trusting any column name in ingest.py.

Usage:
    python -m ffrank.probe              # probes LAST_COMPLETED_SEASON
    python -m ffrank.probe 2024
"""
from __future__ import annotations

import sys

import nflreadpy as nfl

from .config import LAST_COMPLETED_SEASON


def _show(name: str, df, want: list[str] | None = None) -> None:
    cols = list(df.columns)
    print(f"\n{'=' * 70}\n{name}  —  shape={df.shape}\n{'=' * 70}")
    print("columns:")
    for c in cols:
        print(f"  - {c}")
    if want:
        missing = [w for w in want if w not in cols]
        present = [w for w in want if w in cols]
        print(f"\n  EXPECTED present: {present}")
        print(f"  EXPECTED missing: {missing}")
    # Print a couple of rows for shape intuition (polars -> dicts).
    try:
        head = df.head(2).to_dicts()
        for i, r in enumerate(head):
            print(f"\n  sample[{i}]: {{")
            for k, v in r.items():
                print(f"      {k!r}: {v!r}")
            print("  }")
    except Exception as e:  # pragma: no cover - diagnostic only
        print(f"  (could not render sample rows: {e})")


def main(season: int) -> None:
    print(f"nflreadpy version: {getattr(nfl, '__version__', '?')}")
    print(f"Probing season {season}\n")

    _show(
        "load_player_stats(summary_level='reg')",
        nfl.load_player_stats(seasons=[season], summary_level="reg"),
        want=[
            "player_id", "player_name", "player_display_name", "position", "team",
            "games", "fantasy_points", "fantasy_points_ppr",
            "passing_yards", "passing_tds", "passing_interceptions",
            "rushing_yards", "rushing_tds", "carries",
            "receptions", "targets", "receiving_yards", "receiving_tds",
            "rushing_fumbles_lost", "receiving_fumbles_lost", "sack_fumbles_lost",
        ],
    )
    _show(
        "load_snap_counts",
        nfl.load_snap_counts(seasons=[season]),
        want=["pfr_player_id", "player", "position", "team", "offense_snaps", "offense_pct"],
    )
    _show(
        "load_players",
        nfl.load_players(),
        want=["gsis_id", "display_name", "position", "birth_date", "rookie_year",
              "draft_number", "latest_team", "team_abbr"],
    )
    _show(
        "load_ff_playerids",
        nfl.load_ff_playerids(),
        want=["sleeper_id", "gsis_id", "name", "position", "team", "age", "draft_year"],
    )
    _show(
        "load_draft_picks",
        nfl.load_draft_picks(seasons=[season]),
        want=["season", "round", "pick", "gsis_id", "pfr_player_id", "position", "team"],
    )


if __name__ == "__main__":
    s = int(sys.argv[1]) if len(sys.argv) > 1 else LAST_COMPLETED_SEASON
    main(s)

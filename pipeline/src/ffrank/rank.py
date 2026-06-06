"""Produce base_points rankings for an upcoming season and emit a contract-shaped JSON.

This is the slice-1 capstone: it runs the verified ingestion + projection engine forward
(no actuals exist yet for the target season) and writes a JSON that validates against the
locked contract — populating exactly the fields this slice owns (raw_stats + base_points).
Downstream slices fill situation / adjusted_points / vorp / ranks / tiers / market.

Usage:
    python -m ffrank.rank                       # project CURRENT_SEASON, print + write JSON
    python -m ffrank.rank --season 2026 --top 30
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .config import CURRENT_SEASON, DEFAULT_LEAGUE, DEFAULT_SCORING
from .ingest import build_histories
from .project import project_base_points
from .ranking import build_board
from .schema import Contract, Meta, Player, Projection, RawStats

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


def build_contract(season: int) -> Contract:
    players: list[Player] = []
    for pos in SKILL_POSITIONS:
        for h in build_histories(season, DEFAULT_SCORING, position=pos):
            seasons = sorted(h.seasons, key=lambda s: s.season)
            prior = [round(s.points, 1) for s in seasons]
            last = seasons[-1] if seasons else None
            base = round(project_base_points(h), 1)
            players.append(
                Player(
                    id=h.player_id,
                    name=h.name,
                    position=h.position,  # type: ignore[arg-type]
                    team=h.team,
                    age=h.age,
                    is_rookie=h.is_rookie,
                    raw_stats=RawStats(
                        last_season_points=round(last.points, 1) if last else None,
                        games_played=last.games if last else None,
                        snap_share=round(h.last_snap_share, 3) if h.last_snap_share is not None else None,
                        target_share=round(h.last_target_share, 3) if h.last_target_share is not None else None,
                        prior_seasons_points=prior,
                    ),
                    projection=Projection(base_points=base),
                )
            )
    # VORP -> overall/position ranks -> tiers (operates on base_points until soft signals land).
    build_board(players, DEFAULT_LEAGUE)
    players.sort(key=lambda p: p.projection.overall_rank or 10**9)

    meta = Meta(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        season=season,
        scoring_config=DEFAULT_SCORING,
        league_config=DEFAULT_LEAGUE,
    )
    return Contract(meta=meta, players=players)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=CURRENT_SEASON)
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    contract = build_contract(args.season)

    # Human-readable eyeball check.
    print(f"\nDraft board — {args.season} (Full PPR, 12-team; veterans only; rookies = later slice)\n")
    print(f"=== OVERALL (VBD / VORP, top {args.top}) ===")
    for p in contract.players[: args.top]:
        age = f"{p.age:.0f}" if p.age is not None else "??"
        print(f"  {p.projection.overall_rank:3d}. {p.name:24s} {p.position:2s} {p.team:3s} "
              f"age {age}  pts {p.projection.base_points:6.1f}  vorp {p.projection.vorp:6.1f}  T{p.projection.tier}")
    print()

    by_pos: dict[str, list[Player]] = {}
    for p in contract.players:
        by_pos.setdefault(p.position, []).append(p)
    for pos in SKILL_POSITIONS:
        group = sorted(by_pos.get(pos, []), key=lambda p: p.projection.position_rank or 10**9)
        print(f"=== {pos} (top {args.top}, by tier) ===")
        for p in group[: args.top]:
            age = f"{p.age:.0f}" if p.age is not None else "??"
            print(f"  T{p.projection.tier} {p.projection.position_rank:2d}. {p.name:24s} {p.team:3s} "
                  f"age {age}  pts {p.projection.base_points:6.1f}  vorp {p.projection.vorp:6.1f}")
        print()

    if not args.no_write:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUTPUT_DIR / f"rankings_{args.season}_ppr.json"
        out.write_text(contract.model_dump_json(indent=2))
        print(f"Wrote {len(contract.players)} players -> {out}")


if __name__ == "__main__":
    main()

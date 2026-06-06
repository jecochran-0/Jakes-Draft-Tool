"""Produce rankings for an upcoming season and emit a contract-shaped JSON.

Runs the verified ingestion + projection engine forward, builds the value-based draft board
(VORP -> ranks -> tiers), and joins live ADP for the `market` block (value vs ADP). Writes a
JSON that validates against the locked contract. Still deferred: situation / adjusted_points
(soft-signals slice) and the Next.js app.

Usage:
    python -m ffrank.rank                       # project CURRENT_SEASON, print + write JSON
    python -m ffrank.rank --season 2026 --top 30
    python -m ffrank.rank --no-adp              # skip the ADP fetch (offline)
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import requests

from .adp import attach_market, fetch_adp
from .config import CURRENT_SEASON, DEFAULT_LEAGUE, DEFAULT_SCORING
from .ingest import build_histories
from .project import project_base_points
from .ranking import build_board
from .schema import Contract, Meta, Player, Projection, RawStats

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


def build_contract(season: int, with_adp: bool = True) -> Contract:
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

    # Live ADP join -> market block. Build step, not request time. Never hard-fail on network.
    if with_adp:
        try:
            payload = fetch_adp(scoring_key="ppr", teams=DEFAULT_LEAGUE.teams)
            matched, total = attach_market(players, payload)
            meta_info = payload.get("meta", {})
            print(f"ADP: matched {matched}/{total} skill players "
                  f"({meta_info.get('total_drafts')} drafts, {meta_info.get('start_date')}..{meta_info.get('end_date')})")
        except requests.RequestException as e:
            print(f"ADP: fetch failed ({e}); market left null")

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
    ap.add_argument("--no-adp", action="store_true", help="skip the live ADP fetch (offline)")
    args = ap.parse_args()

    contract = build_contract(args.season, with_adp=not args.no_adp)

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

    # Value vs ADP. Bound the display to draftable players: overall_rank runs to ~850 but ADP
    # only covers ~150, so deep players produce meaningless magnitudes. The biggest such gaps
    # are rookies / 2nd-year breakout bets the veteran stat-model can't see (the rookie &
    # soft-signals slices address that) — count them, don't let them swamp the view.
    DRAFTABLE_BOUND = 180
    priced = [p for p in contract.players if p.market and p.market.value_vs_adp is not None]
    draftable = [p for p in priced if p.projection.overall_rank <= DRAFTABLE_BOUND]
    market_only = len(priced) - len(draftable)
    if draftable:
        steals = sorted(draftable, key=lambda p: p.market.value_vs_adp, reverse=True)[:10]
        reaches = sorted(draftable, key=lambda p: p.market.value_vs_adp)[:10]
        print(f"=== BIGGEST VALUES vs ADP — among our top {DRAFTABLE_BOUND} (market drafts them later than we rank) ===")
        for p in steals:
            print(f"  +{p.market.value_vs_adp:>3} {p.name:22s} {p.position:2s}  "
                  f"our #{p.projection.overall_rank:<3d} | adp #{p.market.adp_rank} ({p.market.adp})")
        print(f"\n=== BIGGEST REACHES vs ADP — among our top {DRAFTABLE_BOUND} (market drafts them earlier than we rank) ===")
        for p in reaches:
            print(f"  {p.market.value_vs_adp:>4} {p.name:22s} {p.position:2s}  "
                  f"our #{p.projection.overall_rank:<3d} | adp #{p.market.adp_rank} ({p.market.adp})")
        if market_only:
            print(f"\n  ({market_only} ADP players ranked outside our top {DRAFTABLE_BOUND} — mostly rookies / "
                  f"breakout bets the veteran stat-model can't yet see; value_vs_adp still in the JSON.)")
        print()

    if not args.no_write:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUTPUT_DIR / f"rankings_{args.season}_ppr.json"
        out.write_text(contract.model_dump_json(indent=2))
        print(f"Wrote {len(contract.players)} players -> {out}")


if __name__ == "__main__":
    main()

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
from .config import CURRENT_SEASON, DEFAULT_LEAGUE, scoring_for
from .espn_adp import fetch_espn_adp
from .ingest import build_histories, build_rookie_histories
from .project import PlayerHistory, project_base_points
from .ranking import build_board
from .schema import Contract, Meta, Player, Projection, RawStats
from .softsignals import (apply_soft_scores, attach_situation, audit, compute_soft_scores,
                          load_player_overrides, load_team_ratings)
from .vegas import (attach_vegas, derive_team_totals, fetch_odds, finalize_adjusted,
                    has_api_key, new_env_player_ids)

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "output"
SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


def _player_from_history(h: PlayerHistory, scoring_key: str = "ppr") -> Player:
    seasons = sorted(h.seasons, key=lambda s: s.season)
    prior = [round(s.points, 1) for s in seasons]
    last = seasons[-1] if seasons else None
    return Player(
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
        projection=Projection(base_points=round(project_base_points(h, scoring_key), 1)),
    )


MIN_ADP_MATCH = 80  # below this an ADP source is treated as unusable -> fall back


def _join_adp(players: list[Player], season: int, scoring_key: str, prefer: str = "espn") -> str | None:
    """Attach the market block from the preferred ADP source, falling back to the other.
    Returns the source actually used ('espn'/'ffc') or None. Never hard-fails."""
    def try_espn() -> str | None:
        payload = fetch_espn_adp(scoring_key=scoring_key, season=season)
        matched, total = attach_market(players, payload)
        m = payload.get("meta", {})
        if matched >= MIN_ADP_MATCH:
            print(f"ADP: ESPN {m.get('metric')} — matched {matched}/{total} skill players")
            return "espn"
        print(f"ADP: ESPN matched only {matched}/{total}; falling back")
        return None

    def try_ffc() -> str | None:
        payload = fetch_adp(scoring_key=scoring_key, teams=DEFAULT_LEAGUE.teams)
        matched, total = attach_market(players, payload)
        mi = payload.get("meta", {})
        print(f"ADP: FFC — matched {matched}/{total} skill players ({mi.get('total_drafts')} drafts)")
        return "ffc" if matched >= MIN_ADP_MATCH else None

    order = ["espn", "ffc"] if prefer == "espn" else ["ffc", "espn"]
    for src in order:
        try:
            used = (try_espn if src == "espn" else try_ffc)()
            if used:
                return used
        except requests.RequestException as e:
            print(f"ADP: {src} fetch failed ({e})")
        for p in players:  # clear any partial attach before trying the fallback
            p.market = None
    print("ADP: no source available; market left null")
    return None


def build_contract(season: int, scoring_key: str = "ppr", with_adp: bool = True,
                   with_rookies: bool = True, with_vegas: bool = True,
                   with_soft: bool = True, adp_prefer: str = "espn") -> Contract:
    scoring = scoring_for(scoring_key)
    histories: list[PlayerHistory] = []
    for pos in SKILL_POSITIONS:
        histories.extend(build_histories(season, scoring, position=pos))
    if with_rookies:
        histories.extend(build_rookie_histories(season))

    players = [_player_from_history(h, scoring_key) for h in histories]
    # Players whose current environment isn't in their stats (rookies + team-changers) get the
    # Vegas tilt; stay-put veterans don't (their offense is already in base_points).
    new_env_ids = new_env_player_ids(histories)
    for p in players:
        p.new_env = p.id in new_env_ids

    # Manual situational ratings (1-5) from the two committed files. attach_situation records the
    # six factors on each player for display; compute applies the weighted multiplier below.
    team_ratings = load_team_ratings()
    player_overrides = load_player_overrides()
    attach_situation(players, team_ratings, player_overrides)

    # Vegas team totals -> situation.vegas_team_total + the mechanical tilt below.
    # Only runs if THE_ODDS_API_KEY is set; offseason returns no games -> null. Never hard-fails.
    team_totals: dict[str, float] = {}
    if with_vegas and has_api_key():
        try:
            events = fetch_odds()
            team_totals = derive_team_totals(events)
            n = attach_vegas(players, team_totals)
            print(f"Vegas: {len(team_totals)} teams with totals from {len(events)} games -> set on {n} players"
                  + ("" if events else " (no games posted — offseason?)"))
        except (requests.RequestException, RuntimeError) as e:
            print(f"Vegas: fetch failed ({e}); vegas_team_total left null")
    elif with_vegas:
        print("Vegas: THE_ODDS_API_KEY not set; skipping (vegas_team_total left null)")

    # Manual soft ratings -> per-player soft_score (only players with a net effect). Neutral
    # ratings are a no-op, so this is safe to run unconditionally (the board reflects whatever
    # is committed). --no-soft skips it entirely (ranks on base).
    if with_soft:
        scores = compute_soft_scores(players, team_ratings, player_overrides, new_env_ids)
        applied = apply_soft_scores(players, scores)
        if applied:
            print(f"Soft signals: rated {applied} players (composed with Vegas into adjusted_points)")

    # Single place adjusted_points is set: base x targeted-Vegas x soft. Then rank on adjusted.
    adjusted_n = finalize_adjusted(players, team_totals, new_env_ids)
    build_board(players, DEFAULT_LEAGUE)
    if adjusted_n:
        _print_audit(players)

    players.sort(key=lambda p: p.projection.overall_rank or 10**9)

    # Live ADP join -> market block (value_vs_adp uses the FINAL overall_rank). Never hard-fail.
    # Market reference defaults to ESPN (matches an ESPN draft), falling back to FFC.
    adp_source = _join_adp(players, season, scoring_key, adp_prefer) if with_adp else None

    meta = Meta(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        season=season,
        scoring_config=scoring,
        league_config=DEFAULT_LEAGUE,
        team_situations=team_ratings,
        adp_source=adp_source,
    )
    return Contract(meta=meta, players=players)


def _eff(p: Player) -> float:
    """Effective projection used for ranking: adjusted_points if soft signals set it, else base."""
    return p.projection.adjusted_points if p.projection.adjusted_points is not None else p.projection.base_points


def _soft_mark(p: Player) -> str:
    return "*" if p.projection.adjusted_points is not None else " "


def _print_audit(players: list[Player]) -> None:
    """Spec §9: surface the biggest base->adjusted moves (Vegas tilt and/or soft score)."""
    movers = audit(players)
    if not movers:
        return
    print("\n=== ADJUSTMENT AUDIT — biggest base->adjusted moves (Vegas + soft) ===")
    for p in movers:
        base, adj = p.projection.base_points, p.projection.adjusted_points
        delta = adj - base
        mult = adj / base if base else 1.0
        reason = (p.situation.soft_reasoning if p.situation else "") or "Vegas team-total tilt"
        print(f"  {delta:+6.1f}  x{mult:.3f}  {p.name:22s} {p.position:2s}  "
              f"{base:.1f}->{adj:.1f}  {reason}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=CURRENT_SEASON)
    ap.add_argument("--scoring", choices=["ppr", "half", "standard"], default="ppr",
                    help="scoring format (one output file per format)")
    ap.add_argument("--top", type=int, default=24)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--no-adp", action="store_true", help="skip the live ADP fetch (offline)")
    ap.add_argument("--adp-source", choices=["espn", "ffc"], default="espn",
                    help="market ADP source (default espn; falls back to the other)")
    ap.add_argument("--no-rookies", action="store_true", help="exclude incoming rookie class")
    ap.add_argument("--no-vegas", action="store_true", help="skip the Vegas team-totals fetch")
    ap.add_argument("--no-soft", action="store_true",
                    help="ignore the manual soft ratings and rank on base_points")
    args = ap.parse_args()

    contract = build_contract(args.season, scoring_key=args.scoring, with_adp=not args.no_adp,
                              with_rookies=not args.no_rookies, with_vegas=not args.no_vegas,
                              with_soft=not args.no_soft, adp_prefer=args.adp_source)

    # Human-readable eyeball check.
    print(f"\nDraft board — {args.season} (Full PPR, 12-team; veterans only; rookies = later slice)\n")
    print(f"=== OVERALL (VBD / VORP, top {args.top}) — R = rookie, * = soft-adjusted ===")
    for p in contract.players[: args.top]:
        age = f"{p.age:.0f}" if p.age is not None else "??"
        flag = "R" if p.is_rookie else " "
        print(f"  {p.projection.overall_rank:3d}.{flag} {p.name:24s} {p.position:2s} {p.team:3s} "
              f"age {age}  pts {_eff(p):6.1f}{_soft_mark(p)} vorp {p.projection.vorp:6.1f}  T{p.projection.tier}")
    print()

    by_pos: dict[str, list[Player]] = {}
    for p in contract.players:
        by_pos.setdefault(p.position, []).append(p)
    for pos in SKILL_POSITIONS:
        group = sorted(by_pos.get(pos, []), key=lambda p: p.projection.position_rank or 10**9)
        print(f"=== {pos} (top {args.top}, by tier) — R = rookie, * = soft-adjusted ===")
        for p in group[: args.top]:
            age = f"{p.age:.0f}" if p.age is not None else "??"
            flag = "R" if p.is_rookie else " "
            print(f"  T{p.projection.tier} {p.projection.position_rank:2d}.{flag} {p.name:24s} {p.team:3s} "
                  f"age {age}  pts {_eff(p):6.1f}{_soft_mark(p)} vorp {p.projection.vorp:6.1f}")
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
        out = OUTPUT_DIR / f"rankings_{args.season}_{args.scoring}.json"
        out.write_text(contract.model_dump_json(indent=2))
        print(f"Wrote {len(contract.players)} players -> {out}")


if __name__ == "__main__":
    main()

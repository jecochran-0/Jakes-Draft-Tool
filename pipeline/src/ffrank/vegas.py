"""Vegas team totals -> situation.vegas_team_total (spec §4 Vegas, build step 5).

The Odds API (free tier, us region) exposes GAME totals + spreads, not team totals, so we
derive the implied team total:  team_total = game_total/2 - team_spread/2  (the favorite's
negative spread raises its implied total). We average across bookmakers per game and across a
team's posted games.

Key handling: reads THE_ODDS_API_KEY from the environment. If unset, the pipeline skips Vegas
and leaves situation.vegas_team_total null — never a hard failure.

Seasonality caveat: per-game NFL lines only exist once games are upcoming (preseason/in-season).
Run in the deep offseason (e.g. June) the odds endpoint returns no games, so team totals come
back empty — expected. A pre-draft run in August picks up the early-season slate.

Endpoint:
    GET https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds
        ?apiKey=...&regions=us&markets=totals,spreads&oddsFormat=american
"""
from __future__ import annotations

import os
from statistics import mean

import requests

from .schema import Player, Situation

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
API_KEY_ENV = "THE_ODDS_API_KEY"

# The Odds API returns full team names; map to the nflverse abbreviations used elsewhere.
TEAM_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LA", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "San Francisco 49ers": "SF", "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def has_api_key() -> bool:
    return bool(os.environ.get(API_KEY_ENV))


def fetch_odds(api_key: str | None = None, regions: str = "us", timeout: float = 20.0) -> list[dict]:
    """Fetch NFL game odds (totals + spreads). Raises requests.RequestException on failure."""
    key = api_key or os.environ.get(API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{API_KEY_ENV} not set")
    params = {"apiKey": key, "regions": regions, "markets": "totals,spreads", "oddsFormat": "american"}
    resp = requests.get(ODDS_URL, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _bookmaker_team_totals(bookmaker: dict, home: str, away: str) -> dict[str, float] | None:
    """Implied team totals from one bookmaker's totals+spreads, or None if either is missing."""
    game_total = None
    spreads: dict[str, float] = {}
    for market in bookmaker.get("markets", []):
        if market["key"] == "totals":
            for o in market["outcomes"]:
                if o.get("point") is not None:
                    game_total = float(o["point"])  # Over/Under share the same line
                    break
        elif market["key"] == "spreads":
            for o in market["outcomes"]:
                if o.get("point") is not None:
                    spreads[o["name"]] = float(o["point"])
    if game_total is None or home not in spreads or away not in spreads:
        return None
    return {
        home: game_total / 2 - spreads[home] / 2,
        away: game_total / 2 - spreads[away] / 2,
    }


def derive_team_totals(events: list[dict]) -> dict[str, float]:
    """Map nflverse abbrev -> implied team total, averaged over bookmakers and posted games."""
    per_team: dict[str, list[float]] = {}
    for ev in events:
        home, away = ev.get("home_team"), ev.get("away_team")
        if not home or not away:
            continue
        game_vals: dict[str, list[float]] = {home: [], away: []}
        for bm in ev.get("bookmakers", []):
            tt = _bookmaker_team_totals(bm, home, away)
            if tt:
                game_vals[home].append(tt[home])
                game_vals[away].append(tt[away])
        for full_name, vals in game_vals.items():
            abbr = TEAM_ABBR.get(full_name)
            if abbr and vals:
                per_team.setdefault(abbr, []).append(mean(vals))
    return {abbr: round(mean(vals), 1) for abbr, vals in per_team.items() if vals}


def attach_vegas(players: list[Player], team_totals: dict[str, float]) -> int:
    """Set situation.vegas_team_total for players whose team has a line. Returns count set."""
    n = 0
    for p in players:
        total = team_totals.get(p.team)
        if total is None:
            continue
        if p.situation is None:
            p.situation = Situation()
        p.situation.vegas_team_total = total
        n += 1
    return n


# ----- Mechanical Vegas factor + unified adjusted_points (targeted, option B) ----------------

# A team's implied total is a proxy for offensive quality. We tilt projections toward it, but
# clamped small and applied ONLY where it's NEW information (see new_env_player_ids) so we don't
# double-count the offense already baked into a stay-put veteran's historical points.
VEGAS_SENSITIVITY = 0.5          # fraction of the team's total-vs-average gap to pass through
VEGAS_CLAMP = (0.92, 1.08)       # +/-8% hard bound


def league_average(team_totals: dict[str, float]) -> float | None:
    return mean(team_totals.values()) if team_totals else None


def vegas_multiplier(team_total: float, league_avg: float | None) -> float:
    """Clamped multiplier from a team's total relative to the league average. 1.0 if no average."""
    if not league_avg or league_avg <= 0:
        return 1.0
    raw = 1.0 + VEGAS_SENSITIVITY * (team_total / league_avg - 1.0)
    lo, hi = VEGAS_CLAMP
    return round(max(lo, min(hi, raw)), 4)


def new_env_player_ids(histories) -> set[str]:
    """Players whose CURRENT environment isn't reflected in their stats: rookies (no history)
    and team-changers (history is on a different team). Only these get the Vegas tilt."""
    ids: set[str] = set()
    for h in histories:
        if h.is_rookie or (h.last_stats_team and h.team and h.last_stats_team != h.team):
            ids.add(h.player_id)
    return ids


def finalize_adjusted(players: list[Player], team_totals: dict[str, float],
                      new_env_ids: set[str]) -> int:
    """Set adjusted_points = base x vegas_mult x soft_mult (spec §6b), the single place adjusted
    is computed. vegas_mult tilts only new-environment players; soft_mult comes from the (already
    clamped) situation.soft_score. adjusted stays None when both factors are 1.0 -> the board
    ranks on base. Returns the number of players given an adjusted value."""
    avg = league_average(team_totals)
    n = 0
    for p in players:
        vmult = 1.0
        if team_totals and p.id in new_env_ids and p.team in team_totals:
            vmult = vegas_multiplier(team_totals[p.team], avg)
        soft = p.situation.soft_score if (p.situation and p.situation.soft_score is not None) else None
        smult = soft if soft is not None else 1.0
        if vmult != 1.0 or smult != 1.0:
            p.projection.adjusted_points = round(p.projection.base_points * vmult * smult, 1)
            n += 1
        else:
            p.projection.adjusted_points = None
    return n

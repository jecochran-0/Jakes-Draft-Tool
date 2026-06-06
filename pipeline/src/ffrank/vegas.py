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

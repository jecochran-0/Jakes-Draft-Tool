"""ESPN ADP / draft-rank source — the market reference that matches an ESPN draft.

FantasyFootballCalculator (adp.py) is national *mock* ADP; if you draft on ESPN, your opponents
draft off ESPN's board, not FFC's. So for the mock-draft bots and the value-vs-ADP view to mean
anything for an ESPN league, the market must be ESPN's. This module reads ESPN's free, public
fantasy endpoint (no key) and emits a payload in the SAME shape as adp.fetch_adp, so the existing
adp.attach_market joins it unchanged.

Endpoint (public, read-only):
    GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/
        leaguedefaults/3?view=kona_player_info
    header x-fantasy-filter: {"players":{"limit":N,"sortDraftRanks":{...,"value":"PPR"}}}

Two ESPN signals, in priority order:
  - `ownership.averageDraftPosition` — true ADP. Populated only in draft season (~Jul–Sep); in the
    offseason ESPN returns a uniform placeholder (e.g. 170.0 for everyone).
  - `draftRanksByRankType[FMT].rank` — ESPN's own draft RANK. Populated year-round (Chase = 1).
We use live ADP when it's actually populated (real spread), else ESPN's draft rank — still ESPN's
market, just their published board instead of realized picks. rank.py falls back to FFC only if
ESPN is unreachable / matches too few players.
"""
from __future__ import annotations

from statistics import pstdev

import requests

ESPN_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/"
            "{season}/segments/0/leaguedefaults/3")

# ESPN defaultPositionId -> our position; draftRanksByRankType key per scoring format
# (ESPN exposes only PPR + STANDARD draft ranks; half-PPR uses PPR as the closest proxy).
ESPN_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
ESPN_RANK_TYPE = {"ppr": "PPR", "half": "PPR", "standard": "STANDARD"}

# averageDraftPosition is "live" only when its values actually spread out; in the offseason every
# player shares one placeholder value (stdev ~ 0), so we fall back to ESPN's draft rank.
_LIVE_ADP_STDEV = 3.0


def _fantasy_filter(rank_type: str, limit: int) -> str:
    import json
    return json.dumps({
        "players": {
            "limit": limit,
            "sortDraftRanks": {"sortPriority": 1, "sortAsc": True, "value": rank_type},
        }
    })


def fetch_espn_payload(season: int, rank_type: str, limit: int = 300, timeout: float = 20.0) -> dict:
    """Raw ESPN kona_player_info JSON. Raises requests.RequestException on failure."""
    headers = {
        "x-fantasy-filter": _fantasy_filter(rank_type, limit),
        "accept": "application/json",
        "user-agent": "Mozilla/5.0 (ffrank draft tool)",
    }
    resp = requests.get(ESPN_URL.format(season=season), headers=headers,
                        params={"view": "kona_player_info"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse_espn(raw: dict, scoring_key: str = "ppr") -> dict:
    """Turn ESPN's payload into an FFC-shaped {status, meta, players:[{name,position,adp}]}.

    Pure (no network) so it's unit-testable. Picks live ADP when populated, else ESPN draft rank.
    """
    rank_type = ESPN_RANK_TYPE.get(scoring_key, "PPR")
    entries = raw.get("players", [])
    skill = []
    for e in entries:
        p = e.get("player", {})
        pos = ESPN_POS.get(p.get("defaultPositionId"))
        if not pos:
            continue
        rank = ((p.get("draftRanksByRankType") or {}).get(rank_type) or {}).get("rank")
        adp_live = (p.get("ownership") or {}).get("averageDraftPosition")
        skill.append({"name": p.get("fullName", ""), "position": pos,
                      "rank": rank, "adp_live": adp_live})

    live_vals = [s["adp_live"] for s in skill if isinstance(s["adp_live"], (int, float))]
    live = len(set(live_vals)) > 1 and pstdev(live_vals) > _LIVE_ADP_STDEV

    players = []
    for s in skill:
        value = s["adp_live"] if live else s["rank"]
        if value is None or not s["name"]:
            continue
        players.append({"name": s["name"], "position": s["position"], "adp": float(value)})
    players.sort(key=lambda r: r["adp"])

    return {
        "status": "ok",
        "meta": {"source": "espn", "live_adp": live, "metric": "ADP" if live else "draft rank",
                 "rank_type": rank_type, "count": len(players)},
        "players": players,
    }


def fetch_espn_adp(scoring_key: str = "ppr", season: int = 2026, limit: int = 300,
                   timeout: float = 20.0) -> dict:
    """Fetch + parse ESPN ADP for the season, FFC-shaped for adp.attach_market."""
    rank_type = ESPN_RANK_TYPE.get(scoring_key, "PPR")
    raw = fetch_espn_payload(season, rank_type, limit=limit, timeout=timeout)
    return parse_espn(raw, scoring_key)

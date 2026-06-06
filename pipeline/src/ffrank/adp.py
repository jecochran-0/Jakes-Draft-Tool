"""ADP (average draft position) -> the `market` block (spec §5 market, build step 4).

Source: FantasyFootballCalculator's free public API (no key). The spec named Sleeper, but its
VERIFY clause won out: Sleeper exposes leagues/drafts/players + stable ids, but NO public ADP
endpoint, and nflreadpy's load_ff_rankings is ECR, not ADP. FFC returns ~150-175 PPR players
with real ADP aggregated over hundreds of drafts — exactly the spec's target pool.

  GET https://fantasyfootballcalculator.com/api/v1/adp/{format}?teams={teams}&year={year}
  -> { status, meta{type,teams,total_drafts,...}, players:[{name,position,team,adp,...}] }

FFC has no nflverse/sleeper ids, so we match to our players by normalized name + position.
The same normalizer is applied to BOTH sides, so identically-spelled names always match;
genuine spelling variants (a handful) are reported as unmatched, not silently dropped.

This runs at BUILD time (when generating the JSON), not request time. value_vs_adp needs
overall_rank, so attach_market must run AFTER ranking.build_board.
"""
from __future__ import annotations

import re

import requests

from .schema import Market, Player

SKILL_POSITIONS = {"QB", "RB", "WR", "TE"}
FFC_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}"

# Our ScoringConfig -> FFC format slug.
FORMAT_SLUG = {"ppr": "ppr", "half": "half-ppr", "standard": "standard"}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation and generational suffixes, collapse whitespace.

    Applied symmetrically to our names and FFC names so consistent spellings always match.
    "Ja'Marr Chase" -> "jamarr chase"; "Amon-Ra St. Brown" -> "amonra st brown".
    """
    s = name.lower().replace("'", "").replace(".", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _SUFFIXES]
    return " ".join(tokens)


def fetch_adp(scoring_key: str = "ppr", teams: int = 12, year: int | None = None,
              timeout: float = 20.0) -> dict:
    """Fetch raw ADP. Returns the parsed FFC payload ({status, meta, players}).

    Raises requests.RequestException on network failure — callers decide whether to proceed
    with market=null (the pipeline should not hard-fail just because ADP is unreachable).
    """
    fmt = FORMAT_SLUG.get(scoring_key, "ppr")
    params = {"teams": teams}
    if year is not None:
        params["year"] = year
    resp = requests.get(FFC_URL.format(fmt=fmt), params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def attach_market(players: list[Player], adp_payload: dict) -> tuple[int, int]:
    """Populate p.market for matched players. Returns (matched, total_skill_adp_players).

    adp_rank is the 1-based rank among skill-position ADP players (DST/K excluded so it lines
    up with our skill-only overall_rank). value_vs_adp = adp_rank - overall_rank (positive =
    market drafts him later than we rank him = value/steal).
    """
    rows = [r for r in adp_payload.get("players", []) if r.get("position") in SKILL_POSITIONS]
    rows.sort(key=lambda r: r["adp"])

    index: dict[tuple[str, str], tuple[float, int]] = {}
    for rank, r in enumerate(rows, 1):
        index[(normalize_name(r["name"]), r["position"])] = (float(r["adp"]), rank)

    matched = 0
    for p in players:
        hit = index.get((normalize_name(p.name), p.position))
        if hit is None:
            continue
        adp, adp_rank = hit
        vva = (adp_rank - p.projection.overall_rank) if p.projection.overall_rank is not None else None
        p.market = Market(adp=adp, adp_rank=adp_rank, value_vs_adp=vva)
        matched += 1
    return matched, len(rows)

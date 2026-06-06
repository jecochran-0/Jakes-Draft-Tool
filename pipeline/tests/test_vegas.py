"""Vegas team-total derivation + join + the targeted adjustment factor (offline)."""
from dataclasses import dataclass

from ffrank.schema import Player, Projection, RawStats, Situation
from ffrank.vegas import (attach_vegas, derive_team_totals, finalize_adjusted, league_average,
                          new_env_player_ids, vegas_multiplier)


def _event(home, away, game_total, home_spread):
    """One synthetic event with a single bookmaker carrying totals + spreads."""
    return {
        "home_team": home, "away_team": away,
        "bookmakers": [{
            "key": "bk", "markets": [
                {"key": "totals", "outcomes": [
                    {"name": "Over", "point": game_total},
                    {"name": "Under", "point": game_total},
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": home, "point": home_spread},
                    {"name": away, "point": -home_spread},
                ]},
            ],
        }],
    }


def test_team_total_derivation_math():
    # game total 47.5, home favored by 3.5 (spread -3.5).
    # home total = 47.5/2 - (-3.5)/2 = 23.75 + 1.75 = 25.5; away = 23.75 - 1.75 = 22.0
    events = [_event("Kansas City Chiefs", "Baltimore Ravens", 47.5, -3.5)]
    totals = derive_team_totals(events)
    assert totals["KC"] == 25.5
    assert totals["BAL"] == 22.0
    # The two team totals sum back to the game total.
    assert round(totals["KC"] + totals["BAL"], 1) == 47.5


def test_pickem_splits_evenly():
    events = [_event("Dallas Cowboys", "New York Giants", 44.0, 0.0)]
    totals = derive_team_totals(events)
    assert totals["DAL"] == 22.0 and totals["NYG"] == 22.0


def test_missing_market_skips_event():
    ev = {"home_team": "Dallas Cowboys", "away_team": "New York Giants",
          "bookmakers": [{"key": "bk", "markets": [
              {"key": "totals", "outcomes": [{"name": "Over", "point": 44.0}]}]}]}  # no spreads
    assert derive_team_totals([ev]) == {}


def test_attach_vegas_sets_situation():
    p = Player(id="x", name="Dak", position="QB", team="DAL", is_rookie=False,
               raw_stats=RawStats(), projection=Projection(base_points=300.0))
    n = attach_vegas([p], {"DAL": 26.0})
    assert n == 1 and p.situation is not None and p.situation.vegas_team_total == 26.0
    # Player on a team with no line is untouched.
    q = Player(id="y", name="Nobody", position="WR", team="ZZZ", is_rookie=False,
               raw_stats=RawStats(), projection=Projection(base_points=100.0))
    assert attach_vegas([q], {"DAL": 26.0}) == 0 and q.situation is None


# ----- targeted Vegas factor (option B) -----------------------------------------------------

@dataclass
class _Hist:
    player_id: str
    is_rookie: bool = False
    team: str = ""
    last_stats_team: str | None = None


def _player(pid, team, base=200.0, soft=None):
    p = Player(id=pid, name=pid, position="WR", team=team, is_rookie=False,
               raw_stats=RawStats(), projection=Projection(base_points=base))
    if soft is not None:
        p.situation = Situation(soft_score=soft)
    return p


def test_vegas_multiplier_clamped_and_centered():
    assert vegas_multiplier(22.5, 22.5) == 1.0           # at average -> neutral
    assert vegas_multiplier(30.0, 22.5) == 1.08          # high total -> clamped to +8%
    assert vegas_multiplier(15.0, 22.5) == 0.92          # low total -> clamped to -8%
    assert vegas_multiplier(24.0, None) == 1.0           # no average -> neutral


def test_new_env_ids_rookies_and_team_changers_only():
    hs = [
        _Hist("rook", is_rookie=True, team="KC"),
        _Hist("moved", team="NYJ", last_stats_team="GB"),     # changed teams
        _Hist("stay", team="DET", last_stats_team="DET"),     # stayed put
    ]
    ids = new_env_player_ids(hs)
    assert ids == {"rook", "moved"}


def test_finalize_applies_vegas_only_to_new_env():
    totals = {"BUF": 28.0, "CAR": 17.0}   # avg 22.5
    moved = _player("moved", "BUF", base=200.0)   # team-changer to a high-total team
    stay = _player("stay", "BUF", base=200.0)     # same high-total team, but stayed put
    finalize_adjusted([moved, stay], totals, {"moved"})
    assert moved.projection.adjusted_points == round(200.0 * 1.08, 1)   # +8% tilt
    assert stay.projection.adjusted_points is None                       # untouched (no double-count)


def test_finalize_composes_vegas_and_soft():
    totals = {"BUF": 28.0, "CAR": 17.0}   # avg 22.5 -> BUF mult 1.08
    p = _player("x", "BUF", base=200.0, soft=1.10)
    finalize_adjusted([p], totals, {"x"})
    assert p.projection.adjusted_points == round(200.0 * 1.08 * 1.10, 1)

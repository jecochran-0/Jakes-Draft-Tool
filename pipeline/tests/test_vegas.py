"""Vegas team-total derivation + join (offline; no network/key)."""
from ffrank.schema import Player, Projection, RawStats
from ffrank.vegas import attach_vegas, derive_team_totals


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

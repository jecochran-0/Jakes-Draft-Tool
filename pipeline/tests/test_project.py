"""Projection engine unit tests (no network)."""
from ffrank.project import (
    PlayerHistory,
    SeasonLine,
    TD_PER_YARD,
    _recency_weights,
    _regressed_points,
    expected_games,
    project_base_points,
    project_rookie,
)


def test_recency_weights_renormalize():
    assert abs(sum(_recency_weights(1)) - 1.0) < 1e-9
    assert abs(sum(_recency_weights(2)) - 1.0) < 1e-9
    assert abs(sum(_recency_weights(3)) - 1.0) < 1e-9
    # Most recent weighted highest.
    w = _recency_weights(3)
    assert w[0] > w[1] > w[2]


def test_per_game_normalization():
    """200 pts in 11 games projects higher than 200 pts in 17 games."""
    injured = PlayerHistory("a", "Injured", "RB", age=25,
                            seasons=[SeasonLine(2024, 200.0, 11)])
    full = PlayerHistory("b", "Full", "RB", age=25,
                         seasons=[SeasonLine(2024, 200.0, 17)])
    assert project_base_points(injured) > project_base_points(full)


def test_rookie_branch_uses_draft_capital():
    early = PlayerHistory("r1", "Early", "RB", age=22, is_rookie=True, draft_pick=5)
    late = PlayerHistory("r2", "Late", "RB", age=22, is_rookie=True, draft_pick=200)
    assert project_rookie(early) > project_rookie(late)


def test_age_decline_for_rb():
    young = PlayerHistory("y", "Young", "RB", age=24,
                          seasons=[SeasonLine(2024, 250.0, 17)])
    old = PlayerHistory("o", "Old", "RB", age=31,
                        seasons=[SeasonLine(2024, 250.0, 17)])
    assert project_base_points(old) < project_base_points(young)


def test_td_regression_pulls_toward_expected():
    """TDs above yardage-expectation are pulled down; below-expectation pulled up."""
    rate = TD_PER_YARD["RB"]["rush"]
    expected = 1000 * rate  # ~7 for 1000 rush yds
    hot = SeasonLine(2024, points=200.0, games=17, rush_yds=1000.0, rush_td=expected + 8)
    cold = SeasonLine(2024, points=200.0, games=17, rush_yds=1000.0, rush_td=max(0.0, expected - 4))
    assert _regressed_points(hot, "RB") < 200.0    # lucky TD spike regressed down
    assert _regressed_points(cold, "RB") > 200.0   # unlucky TD drought regressed up
    # A season with no component data is untouched (back-compat with points-only SeasonLine).
    assert _regressed_points(SeasonLine(2024, 180.0, 17), "RB") == 180.0


def test_expected_games_discounts_fragile_and_old():
    durable = PlayerHistory("d", "Durable", "WR", age=26,
                            seasons=[SeasonLine(2023, 250.0, 17), SeasonLine(2024, 250.0, 17)])
    fragile = PlayerHistory("f", "Fragile", "WR", age=26,
                            seasons=[SeasonLine(2023, 250.0, 10), SeasonLine(2024, 250.0, 9)])
    assert expected_games(durable) == 17.0
    assert expected_games(fragile) < 15.0
    # An older RB is taxed below an identical young RB.
    young = PlayerHistory("y", "Y", "RB", age=24, seasons=[SeasonLine(2024, 250.0, 17)])
    old = PlayerHistory("o", "O", "RB", age=30, seasons=[SeasonLine(2024, 250.0, 17)])
    assert expected_games(old) < expected_games(young)


def test_fragile_player_projects_below_durable_equal_per_game():
    """Same per-game rate, but the oft-injured player now projects lower (availability)."""
    durable = PlayerHistory("d", "Durable", "WR", age=26, seasons=[SeasonLine(2024, 255.0, 17)])
    fragile = PlayerHistory("f", "Fragile", "WR", age=26,
                            seasons=[SeasonLine(2023, 150.0, 10), SeasonLine(2024, 150.0, 10)])
    # Fragile has the higher per-game rate (15.0 vs 15.0) but a worse availability outlook.
    assert expected_games(fragile) < expected_games(durable)
    assert project_base_points(fragile) < project_base_points(durable)

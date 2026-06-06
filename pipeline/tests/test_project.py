"""Projection engine unit tests (no network)."""
from ffrank.project import (
    PlayerHistory,
    SeasonLine,
    _recency_weights,
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

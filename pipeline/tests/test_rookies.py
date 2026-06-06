"""Rookie projection branch + team normalization (offline)."""
from ffrank.ingest import _fix_team
from ffrank.project import PlayerHistory, project_base_points, project_rookie


def test_team_abbrev_normalization():
    assert _fix_team("LVR") == "LV"
    assert _fix_team("NOR") == "NO"
    assert _fix_team("LAR") == "LA"
    assert _fix_team("KC") == "KC"   # already standard -> unchanged
    assert _fix_team(None) == ""


def test_rookie_dispatch_uses_draft_capital_not_seasons():
    # is_rookie with empty seasons -> project_rookie path (draft capital), not veteran blend.
    early = PlayerHistory("r1", "Early Pick", "RB", age=22, is_rookie=True, seasons=[], draft_pick=3)
    late = PlayerHistory("r2", "Late Pick", "RB", age=22, is_rookie=True, seasons=[], draft_pick=180)
    assert project_base_points(early) == project_rookie(early)
    assert project_base_points(early) > project_base_points(late)


def test_rookie_opportunity_factor_scales():
    base = PlayerHistory("r", "Rook", "WR", age=22, is_rookie=True, seasons=[], draft_pick=20,
                         opportunity_factor=1.0)
    boosted = PlayerHistory("r2", "Rook2", "WR", age=22, is_rookie=True, seasons=[], draft_pick=20,
                            opportunity_factor=1.3)
    assert project_rookie(boosted) > project_rookie(base)

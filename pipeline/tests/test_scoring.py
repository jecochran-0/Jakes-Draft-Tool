"""Scoring correctness: our configurable PPR must match nflverse fantasy_points_ppr."""
import pytest

from ffrank.config import DEFAULT_SCORING, scoring_for
from ffrank.ingest import stats_table
from ffrank.scoring import points


def test_scoring_presets():
    assert scoring_for("ppr").rec == 1.0
    assert scoring_for("half").rec == 0.5
    assert scoring_for("standard").rec == 0.0
    with pytest.raises(ValueError):
        scoring_for("superflex")


def test_format_changes_receiving_points():
    # A pure receiving line: 6 catches, 80 yards. PPR=14, Half=11, Standard=8.
    row = {"receptions": 6, "receiving_yards": 80}
    assert points(row, scoring_for("ppr")) == pytest.approx(14.0)
    assert points(row, scoring_for("half")) == pytest.approx(11.0)
    assert points(row, scoring_for("standard")) == pytest.approx(8.0)


def test_ppr_matches_nflverse():
    """For full PPR, our points() should match nflverse fantasy_points_ppr within rounding,
    for the bulk of skill players (small tail differs on rare special-teams/return scoring)."""
    df = stats_table((2024,), DEFAULT_SCORING)
    rows = df.to_dicts()
    rows = [r for r in rows if r["fantasy_points_ppr"] is not None and r["games"]]
    assert len(rows) > 300

    diffs = [abs(r["points"] - r["fantasy_points_ppr"]) for r in rows]
    close = sum(1 for d in diffs if d < 0.5)
    frac = close / len(rows)
    # Expect near-total agreement; allow a small tail for return/ST TDs we don't model.
    assert frac > 0.97, f"only {frac:.3f} of rows matched fantasy_points_ppr"
    assert max(diffs) < 30, f"max scoring diff too large: {max(diffs):.1f}"

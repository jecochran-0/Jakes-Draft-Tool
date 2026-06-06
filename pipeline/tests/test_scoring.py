"""Scoring correctness: our configurable PPR must match nflverse fantasy_points_ppr."""
from ffrank.config import DEFAULT_SCORING
from ffrank.ingest import stats_table


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

"""Replacement-level greedy fill (§6c) sanity checks."""
from ffrank.config import DEFAULT_LEAGUE, compute_replacement_levels


def test_qb_te_replacement_indices():
    # 12 teams, 1 QB + 1 TE per team, no flex draws QB/TE in practice for these pools.
    # Build deep descending pools; replacement should land at the 13th-best (index 12).
    pools = {
        "QB": [300 - i for i in range(40)],
        "TE": [200 - i for i in range(40)],
        "RB": [250 - i for i in range(80)],
        "WR": [250 - i for i in range(80)],
    }
    levels = compute_replacement_levels(pools, DEFAULT_LEAGUE)
    # QB: 12 starters -> replacement is 13th QB = 300 - 12 = 288.
    assert levels["QB"] == 288
    # TE: 12 starters; TEs rarely win flex over RB/WR here -> 13th TE = 200 - 12 = 188.
    assert levels["TE"] == 188


def test_flex_pushes_rb_wr_below_base():
    pools = {
        "QB": [300 - i for i in range(40)],
        "TE": [120 - i for i in range(40)],   # weak TEs never win flex
        "RB": [250 - i for i in range(80)],
        "WR": [248 - i for i in range(80)],
    }
    levels = compute_replacement_levels(pools, DEFAULT_LEAGUE)
    # 24 base RB + 24 base WR starters, then 12 flex split between RB/WR by value.
    # Replacement RB and WR must fall beyond their 24-base (lower points than the 24th).
    assert levels["RB"] < 250 - 24
    assert levels["WR"] < 248 - 24

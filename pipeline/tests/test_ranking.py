"""VORP / ranks / tiers (spec §6c/§6d) — offline."""
from ffrank.config import LeagueConfig
from ffrank.ranking import assign_ranks, assign_tiers, build_board, compute_vorp
from ffrank.schema import Player, Projection, RawStats


def _p(name, pos, pts):
    return Player(id=name, name=name, position=pos, team="X", is_rookie=False,
                  raw_stats=RawStats(), projection=Projection(base_points=pts))


def _board(players, teams=12):
    league = LeagueConfig(teams=teams)
    return build_board(players, league)


def test_vorp_makes_positions_comparable():
    # A deep QB pool means replacement QB is high-scoring -> top QB has modest VORP, while a
    # top RB in a thin pool clears a low replacement by a lot.
    qbs = [_p(f"QB{i}", "QB", 320 - i * 3) for i in range(30)]
    rbs = [_p(f"RB{i}", "RB", 300 - i * 6) for i in range(60)]
    wrs = [_p(f"WR{i}", "WR", 295 - i * 5) for i in range(60)]
    tes = [_p(f"TE{i}", "TE", 200 - i * 5) for i in range(30)]
    players = qbs + rbs + wrs + tes
    _board(players)
    top_qb = min(qbs, key=lambda p: p.projection.overall_rank)
    top_rb = min(rbs, key=lambda p: p.projection.overall_rank)
    # Top RB should out-rank top QB on VORP despite similar raw points.
    assert top_rb.projection.vorp > top_qb.projection.vorp
    assert top_rb.projection.overall_rank < top_qb.projection.overall_rank


def test_overall_and_position_ranks_are_consistent():
    rbs = [_p(f"RB{i}", "RB", 300 - i * 10) for i in range(40)]
    wrs = [_p(f"WR{i}", "WR", 290 - i * 9) for i in range(40)]
    players = rbs + wrs
    _board(players)
    # position_rank 1 == the highest-points player in that position
    best_rb = max(rbs, key=lambda p: p.projection.base_points)
    assert best_rb.projection.position_rank == 1
    # overall ranks are a 1..N permutation
    ranks = sorted(p.projection.overall_rank for p in players)
    assert ranks == list(range(1, len(players) + 1))


def test_tiers_break_on_large_gaps():
    # Two clear clusters with a big gap between them -> at least two tiers, monotonic.
    pts = [300, 298, 296, 250, 248, 246]  # 46-pt cliff after the 3rd player
    rbs = [_p(f"RB{i}", "RB", v) for i, v in enumerate(pts)]
    assign_tiers(rbs)
    rbs.sort(key=lambda p: p.projection.base_points, reverse=True)
    tiers = [p.projection.tier for p in rbs]
    assert tiers[0] == 1 and tiers == sorted(tiers)  # non-decreasing down the board
    assert tiers[3] > tiers[2]                        # the cliff creates a new tier
    assert max(tiers) >= 2


def test_metric_prefers_adjusted_when_present():
    p = _p("A", "RB", 200.0)
    p.projection.adjusted_points = 250.0
    others = [_p(f"RB{i}", "RB", 150 - i) for i in range(30)]
    compute_vorp([p] + others, LeagueConfig())
    # VORP should be based on 250 (adjusted), not 200 (base).
    assert p.projection.vorp is not None and p.projection.vorp > 80

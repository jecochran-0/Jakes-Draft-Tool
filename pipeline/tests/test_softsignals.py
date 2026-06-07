"""Soft signals (spec §6b/§7/§8) — manual 1-5 ratings -> multiplier. Offline."""
import json

from ffrank.ranking import build_board
from ffrank.schema import LeagueConfig, Player, Projection, RawStats
from ffrank.softsignals import (apply_soft_scores, attach_situation, audit, compute_soft_scores,
                                load_player_overrides, load_team_ratings, player_ratings,
                                soft_for_ratings)
from ffrank.vegas import finalize_adjusted


def _p(pid, name, pos, team, base, rank=None, rookie=False):
    p = Player(id=pid, name=name, position=pos, team=team, is_rookie=rookie,
               raw_stats=RawStats(target_share=0.14, snap_share=0.7),
               projection=Projection(base_points=base))
    p.projection.overall_rank = rank
    return p


# ----- loading ---------------------------------------------------------------------------

def test_load_team_ratings_defaults_missing_factors(tmp_path):
    f = tmp_path / "team.json"
    f.write_text(json.dumps([{"team": "ATL", "ol": 5, "notes": "good line"}]))
    table = load_team_ratings(f)
    assert table["ATL"]["ol"] == 5
    assert table["ATL"]["qb"] == 3 and table["ATL"]["scheme"] == 3 and table["ATL"]["pace"] == 3
    assert table["ATL"]["notes"] == "good line"


def test_load_player_overrides(tmp_path):
    f = tmp_path / "ovr.json"
    f.write_text(json.dumps([{"id": "a", "role": 5}, {"id": "b", "competition": 1}]))
    ovr = load_player_overrides(f)
    assert ovr["a"]["role"] == 5 and ovr["a"]["competition"] == 3   # missing -> neutral
    assert ovr["b"]["competition"] == 1


def test_player_ratings_merges_team_and_player():
    p = _p("a", "A", "RB", "ATL", 200.0)
    r = player_ratings(p, {"ATL": {"ol": 5}}, {"a": {"role": 4}})
    assert r["ol"] == 5 and r["role"] == 4
    assert r["qb"] == 3 and r["scheme"] == 3 and r["pace"] == 3 and r["competition"] == 3


# ----- the model -------------------------------------------------------------------------

def test_neutral_ratings_are_a_no_op():
    players = [_p("a", "A", "RB", "ATL", 200.0)]
    assert compute_soft_scores(players, {}, {}) == {}            # nothing rated -> empty
    assert compute_soft_scores(players, {"ATL": {"ol": 3}}, {"a": {"role": 3}}) == {}  # all neutral


def test_maxed_ratings_hit_the_bounds():
    rb = _p("a", "A", "RB", "ATL", 200.0)
    team_max = {"ATL": {"qb": 5, "ol": 5, "scheme": 5, "pace": 5}}
    assert soft_for_ratings(player_ratings(rb, team_max, {"a": {"role": 5, "competition": 5}}), "RB") == 1.15
    team_min = {"ATL": {"qb": 1, "ol": 1, "scheme": 1, "pace": 1}}
    assert soft_for_ratings(player_ratings(rb, team_min, {"a": {"role": 1, "competition": 1}}), "RB") == 0.85


def test_position_weighting_ol_moves_rb_not_wr():
    # OL is weighted for RBs (0.05) but zero for WRs -> identical OL rating moves only the RB.
    rb = _p("a", "Back", "RB", "ATL", 200.0)
    wr = _p("b", "Wide", "WR", "ATL", 200.0)
    scores = compute_soft_scores([rb, wr], {"ATL": {"ol": 5}}, {})
    assert scores["a"][0] == 1.05            # 0.05 * (5-3)/2 = +0.05
    assert "b" not in scores                 # OL weight is 0 for WR -> no net effect


def test_player_override_lifts_that_player():
    rb = _p("a", "A", "RB", "ATL", 200.0)
    scores = compute_soft_scores([rb], {}, {"a": {"role": 5}})
    assert scores["a"][0] == 1.04            # 0.04 * (5-3)/2 = +0.04


def test_reasoning_names_the_driving_factors():
    rb = _p("a", "A", "RB", "ATL", 200.0)
    scores = compute_soft_scores([rb], {"ATL": {"ol": 5}}, {"a": {"competition": 1}})
    reasoning = scores["a"][1]
    assert "OL 5/5" in reasoning and "lift" in reasoning
    assert "competition 1/5" in reasoning and "drag" in reasoning


def test_compute_then_apply_drives_ranking():
    a = _p("a", "Boosted", "WR", "ATL", 200.0)
    b = _p("b", "Faded", "WR", "ATL", 200.0)
    pool = [a, b] + [_p(f"x{i}", f"X{i}", "WR", "BUF", 150 - i) for i in range(40)]
    team = {"ATL": {}}  # ATL neutral; the per-player overrides do the work
    overrides = {"a": {"role": 5, "competition": 5}, "b": {"role": 1, "competition": 1}}
    scores = compute_soft_scores(pool, team, overrides)
    apply_soft_scores(pool, scores)
    finalize_adjusted(pool, {}, set())
    build_board(pool, LeagueConfig())
    assert a.projection.overall_rank < b.projection.overall_rank


# ----- attach / apply / audit ------------------------------------------------------------

def test_attach_situation_records_soft_factors():
    players = [_p("a", "A", "RB", "ATL", 200.0)]
    attach_situation(players, {"ATL": {"ol": 5, "qb": 2}}, {"a": {"role": 4}})
    sf = players[0].situation.soft_factors
    assert sf == {"qb": 2, "ol": 5, "scheme": 3, "pace": 3, "role": 4, "competition": 3}


def test_apply_sets_soft_fields_only():
    players = [_p("a", "A", "RB", "ATL", 200.0), _p("b", "B", "RB", "ATL", 200.0)]
    n = apply_soft_scores(players, {"a": (1.10, "expanded role")})
    assert n == 1
    assert players[0].situation.soft_score == 1.10
    assert players[0].situation.soft_reasoning == "expanded role"
    assert players[0].projection.adjusted_points is None  # not set until finalize
    finalize_adjusted(players, {}, set())
    assert players[0].projection.adjusted_points == 220.0
    assert players[1].projection.adjusted_points is None   # unscored -> ranks on base


def test_audit_orders_by_absolute_move():
    players = [_p("a", "Big", "RB", "ATL", 200.0), _p("b", "Small", "RB", "ATL", 200.0),
               _p("c", "None", "RB", "ATL", 200.0)]
    apply_soft_scores(players, {"a": (1.15, "x"), "b": (1.02, "y")})  # c unscored
    finalize_adjusted(players, {}, set())
    movers = audit(players)
    assert movers[0].id == "a" and movers[1].id == "b"
    assert all(m.projection.adjusted_points is not None for m in movers)

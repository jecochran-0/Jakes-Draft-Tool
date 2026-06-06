"""Soft signals (spec §6b/§7/§8) — offline."""
import json

from ffrank.ranking import build_board
from ffrank.schema import LeagueConfig, Player, Projection, RawStats
from ffrank.softsignals import (SYSTEM_PROMPT, apply_soft_scores, attach_situation, audit,
                                emit_player_prompts, load_soft_scores, load_team_table,
                                situation_facts, team_row)
from ffrank.vegas import finalize_adjusted


def _p(pid, name, pos, team, base, rank=None, rookie=False):
    p = Player(id=pid, name=name, position=pos, team=team, is_rookie=rookie,
               raw_stats=RawStats(target_share=0.14, snap_share=0.7),
               projection=Projection(base_points=base))
    p.projection.overall_rank = rank
    return p


def test_load_soft_scores_clamps_and_keys_by_id(tmp_path):
    f = tmp_path / "scores.json"
    f.write_text(json.dumps([
        {"id": "a", "soft_score": 1.30, "soft_reasoning": "too high -> clamp"},
        {"id": "b", "soft_score": 0.50, "soft_reasoning": "too low -> clamp"},
        {"id": "c", "soft_score": 1.05, "soft_reasoning": "ok"},
        {"id": "d"},  # missing score -> ignored
    ]))
    scores = load_soft_scores(f)
    assert scores["a"][0] == 1.15 and scores["b"][0] == 0.85 and scores["c"][0] == 1.05
    assert "d" not in scores


def test_apply_sets_soft_fields_only():
    # apply_soft_scores sets soft_score/reasoning; finalize_adjusted computes adjusted_points.
    players = [_p("a", "A", "RB", "ATL", 200.0), _p("b", "B", "RB", "ATL", 200.0)]
    n = apply_soft_scores(players, {"a": (1.10, "expanded role")})
    assert n == 1
    assert players[0].situation.soft_score == 1.10
    assert players[0].situation.soft_reasoning == "expanded role"
    assert players[0].projection.adjusted_points is None  # not set yet
    finalize_adjusted(players, {}, set())                 # no Vegas; soft only
    assert players[0].projection.adjusted_points == 220.0
    assert players[1].projection.adjusted_points is None   # unscored -> ranks on base


def test_adjusted_drives_ranking():
    # Identical base; the boosted player must out-rank the faded one after finalize + re-rank.
    a = _p("a", "Boosted", "WR", "ATL", 200.0)
    b = _p("b", "Faded", "WR", "ATL", 200.0)
    pool = [a, b] + [_p(f"x{i}", f"X{i}", "WR", "ATL", 150 - i) for i in range(40)]
    apply_soft_scores(pool, {"a": (1.15, "elite fit"), "b": (0.85, "lost role")})
    finalize_adjusted(pool, {}, set())
    build_board(pool, LeagueConfig())
    assert a.projection.overall_rank < b.projection.overall_rank


def test_emit_batches_and_id_echo(tmp_path):
    players = [_p(f"id{i}", f"P{i}", "RB", "ATL", 200 - i, rank=i + 1) for i in range(100)]
    paths = emit_player_prompts(players, {}, tmp_path, batch_size=45, limit=100)
    assert len(paths) == 3  # 45 + 45 + 10
    first = paths[0].read_text()
    assert SYSTEM_PROMPT.split("\n", 1)[0] in first          # system prompt present
    assert "id: id0" in first and "id: id44" in first        # id echoes present
    assert "id: id45" not in first                            # batch boundary respected


def test_team_table_defaults_and_facts(tmp_path):
    f = tmp_path / "team.json"
    f.write_text(json.dumps([{"team": "ATL", "qb_tier": 2, "oc_change": True,
                              "scheme": "zone run", "notes": "lead back clear"}]))
    table = load_team_table(f)
    assert table["ATL"]["qb_tier"] == 2 and table["ATL"]["oc_change"] is True
    assert team_row(table, "ZZZ")["qb_tier"] == 3  # missing -> neutral default

    p = _p("a", "Bijan", "RB", "ATL", 280.0)
    facts = situation_facts(p, table["ATL"])
    assert "id: a" in facts and "Bijan" in facts
    assert "CHANGED" in facts and "QB tier" in facts and "zone run" in facts


def test_attach_situation_copies_table():
    players = [_p("a", "A", "QB", "BUF", 300.0)]
    attach_situation(players, {"BUF": {"qb_tier": 1, "oc_change": False, "scheme": "", "notes": ""}})
    assert players[0].situation.qb_tier == 1 and players[0].situation.oc_change is False


def test_audit_orders_by_absolute_move():
    players = [_p("a", "Big", "RB", "ATL", 200.0), _p("b", "Small", "RB", "ATL", 200.0),
               _p("c", "None", "RB", "ATL", 200.0)]
    apply_soft_scores(players, {"a": (1.15, "x"), "b": (1.02, "y")})  # c unscored
    finalize_adjusted(players, {}, set())
    movers = audit(players)
    assert movers[0].id == "a" and movers[1].id == "b"
    assert all(m.projection.adjusted_points is not None for m in movers)

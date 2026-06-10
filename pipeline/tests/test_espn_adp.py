"""ESPN ADP parsing (offline — no network)."""
from ffrank.espn_adp import parse_espn


def _player(name, pos_id, adp, rank):
    return {"player": {
        "fullName": name, "defaultPositionId": pos_id,
        "ownership": {"averageDraftPosition": adp},
        "draftRanksByRankType": {"PPR": {"rank": rank}, "STANDARD": {"rank": rank}},
    }}


def test_offseason_falls_back_to_draft_rank():
    # All ADP equal to the placeholder (stdev 0) -> use ESPN draft rank, ordered by it.
    raw = {"players": [
        _player("Player C", 3, 170.0, 3),
        _player("Player A", 2, 170.0, 1),
        _player("Player B", 4, 170.0, 2),
        _player("Kicker", 5, 170.0, 1),  # non-skill -> dropped
    ]}
    out = parse_espn(raw, "ppr")
    assert out["meta"]["live_adp"] is False and out["meta"]["metric"] == "draft rank"
    names = [p["name"] for p in out["players"]]
    assert names == ["Player A", "Player B", "Player C"]  # sorted by rank, kicker excluded
    assert out["players"][0]["adp"] == 1.0 and out["players"][0]["position"] == "RB"


def test_live_adp_used_when_populated():
    raw = {"players": [
        _player("Stud", 2, 1.4, 1),
        _player("Mid", 3, 24.0, 2),
        _player("Late", 4, 95.0, 3),
    ]}
    out = parse_espn(raw, "ppr")
    assert out["meta"]["live_adp"] is True and out["meta"]["metric"] == "ADP"
    assert [p["adp"] for p in out["players"]] == [1.4, 24.0, 95.0]


def test_standard_uses_standard_rank_type():
    raw = {"players": [_player("QB1", 1, 170.0, 5)]}
    out = parse_espn(raw, "standard")
    assert out["meta"]["rank_type"] == "STANDARD"
    assert out["players"][0]["adp"] == 5.0

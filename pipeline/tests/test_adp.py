"""ADP normalization + market join (spec §5 market) — offline, synthetic payload."""
from ffrank.adp import attach_market, normalize_name
from ffrank.schema import Market, Player, Projection, RawStats


def test_normalize_name_handles_punctuation_and_suffixes():
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("Amon-Ra St. Brown") == "amon ra st brown"  # hyphen -> space (symmetric both sides)
    assert normalize_name("Michael Pittman Jr.") == "michael pittman"
    assert normalize_name("Marvin Harrison Jr.") == normalize_name("Marvin Harrison")


def _player(name, pos, overall_rank):
    p = Player(id=name, name=name, position=pos, team="X", is_rookie=False,
               raw_stats=RawStats(), projection=Projection(base_points=100.0))
    p.projection.overall_rank = overall_rank
    return p


def test_value_vs_adp_sign_and_rank():
    # ADP order among skill players: A=1, B=2, C=3 (DST excluded from ranking).
    payload = {"players": [
        {"name": "Early WR", "position": "WR", "adp": 1.4},
        {"name": "Mid RB", "position": "RB", "adp": 2.1},
        {"name": "Late WR", "position": "WR", "adp": 30.0},
        {"name": "Some Defense", "position": "DST", "adp": 5.0},
    ]}
    # Our board ranks them in the OPPOSITE order to create a clear steal and reach.
    players = [
        _player("Early WR", "WR", 3),   # market drafts 1st, we rank 3rd -> reach (negative)
        _player("Mid RB", "RB", 2),     # aligned -> 0
        _player("Late WR", "WR", 1),    # market drafts 3rd/last, we rank 1st -> steal (positive)
    ]
    matched, total = attach_market(players, payload)
    assert matched == 3 and total == 3  # DST excluded from total

    by = {p.name: p for p in players}
    assert by["Early WR"].market.adp_rank == 1 and by["Late WR"].market.adp_rank == 3
    # value_vs_adp = adp_rank - overall_rank. Positive = falls later than we value = steal.
    assert by["Late WR"].market.value_vs_adp == 3 - 1      # +2 steal
    assert by["Mid RB"].market.value_vs_adp == 2 - 2       # 0 aligned
    assert by["Early WR"].market.value_vs_adp == 1 - 3     # -2 reach


def test_unmatched_player_gets_no_market():
    payload = {"players": [{"name": "Real Player", "position": "RB", "adp": 1.0}]}
    p = _player("Unknown Guy", "RB", 50)
    matched, _ = attach_market([p], payload)
    assert matched == 0 and p.market is None


def test_value_vs_adp_null_beyond_draftable_bound():
    from ffrank.adp import VALUE_VS_ADP_BOUND
    payload = {"players": [{"name": "Deep Guy", "position": "WR", "adp": 140.0}]}
    p = _player("Deep Guy", "WR", VALUE_VS_ADP_BOUND + 50)  # we rank him well outside draftable
    attach_market([p], payload)
    # adp / adp_rank still populated, but the misleading huge value_vs_adp is suppressed.
    assert p.market.adp == 140.0 and p.market.adp_rank == 1
    assert p.market.value_vs_adp is None

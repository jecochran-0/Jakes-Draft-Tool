"""The locked contract, sample, and pydantic models must agree (offline)."""
import json
from pathlib import Path

from ffrank.schema import Contract

ROOT = Path(__file__).resolve().parents[2]


def test_sample_validates_against_models():
    sample = json.loads((ROOT / "schema" / "sample.json").read_text())
    contract = Contract.model_validate(sample)
    assert contract.meta.season == 2026
    assert contract.players[0].name == "Bijan Robinson"
    assert contract.players[0].projection.base_points == 268.0


def test_minimal_player_only_needs_base_points():
    """Later-slice fields are optional; a slice-1 player needs only raw_stats + base_points."""
    minimal = {
        "meta": {
            "generated_at": "2026-01-01T00:00:00Z",
            "season": 2026,
            "scoring_config": {},
            "league_config": {},
        },
        "players": [
            {
                "id": "gsis_00-0000000",
                "name": "Test Player",
                "position": "RB",
                "team": "ATL",
                "is_rookie": False,
                "raw_stats": {"prior_seasons_points": [100.0, 120.0]},
                "projection": {"base_points": 150.0},
            }
        ],
    }
    contract = Contract.model_validate(minimal)
    p = contract.players[0]
    assert p.situation is None and p.market is None
    assert p.projection.adjusted_points is None and p.projection.tier is None

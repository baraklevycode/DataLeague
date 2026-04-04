"""Tests for the data processor."""

from fetcher.clients.sport5 import Sport5Client
from fetcher.schemas import Sport5StatsData


def test_parse_stats_data_empty():
    result = Sport5Client.parse_stats_data("")
    assert isinstance(result, Sport5StatsData)
    assert result.Goals.Count == 0


def test_parse_stats_data_valid_json():
    import json
    data = {
        "Goals": {"Count": 5, "Points": 20},
        "Assists": {"Count": 3, "Points": 9},
        "MinutesPlayed": {"Count": 900, "Points": 0},
    }
    result = Sport5Client.parse_stats_data(json.dumps(data))
    assert result.Goals.Count == 5
    assert result.Goals.Points == 20
    assert result.Assists.Count == 3
    assert result.MinutesPlayed.Count == 900


def test_parse_stats_data_double_encoded():
    import json
    data = {
        "Goals": {"Count": 2, "Points": 8},
        "Assists": {"Count": 1, "Points": 3},
    }
    # Double-encoded JSON string
    double_encoded = json.dumps(json.dumps(data))
    result = Sport5Client.parse_stats_data(double_encoded)
    assert result.Goals.Count == 2
    assert result.Assists.Points == 3


def test_parse_stats_data_invalid():
    result = Sport5Client.parse_stats_data("not json at all")
    assert isinstance(result, Sport5StatsData)
    assert result.Goals.Count == 0

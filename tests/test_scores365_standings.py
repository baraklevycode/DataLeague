"""Regression tests for the 365Scores standings flattener.

After the regular season ends the standings API splits the table into
playoff groups (Championship + Relegation), each restarting at
position 1. The UI was showing two teams at #1, two at #2, etc. The
parser now flattens the groups and assigns an overall 1..N position.
"""

from __future__ import annotations

from fetcher.clients.scores365 import parse_standings


def _row(pos: int, cid: int, name: str, pts: float, group: int = 1) -> dict:
    return {
        "groupNum": group,
        "position": pos,
        "gamePlayed": 26,
        "gamesWon": 0,
        "gamesEven": 0,
        "gamesLost": 0,
        "for": 0,
        "against": 0,
        "points": pts,
        "competitor": {"id": cid, "name": name},
        "detailedRecentForm": [],
    }


def test_parse_standings_single_group_regular_season() -> None:
    data = {
        "standings": [
            {"rows": [
                _row(1, 10, "A", 30),
                _row(2, 20, "B", 28),
                _row(3, 30, "C", 25),
            ]}
        ]
    }
    rows = parse_standings(data)
    assert [(r.position, r.competitor_id) for r in rows] == [(1, 10), (2, 20), (3, 30)]


def test_parse_standings_two_playoff_groups_gives_overall_positions() -> None:
    """Championship group (1..6) followed by Relegation group (1..8)
    should be flattened into overall positions 1..14 - each team unique."""
    data = {
        "standings": [
            {"rows": [
                _row(1, 101, "HBS", 59, group=1),
                _row(2, 102, "BEI", 57, group=1),
                _row(3, 103, "MTA", 49, group=1),
                _row(1, 201, "MNE", 35, group=2),
                _row(2, 202, "BnS", 32, group=2),
                _row(3, 203, "IKS", 27, group=2),
            ]}
        ]
    }
    rows = parse_standings(data)
    assert [(r.position, r.competitor_id, r.points) for r in rows] == [
        (1, 101, 59),
        (2, 102, 57),
        (3, 103, 49),
        (4, 201, 35),
        (5, 202, 32),
        (6, 203, 27),
    ]


def test_parse_standings_preserves_within_group_order_when_rows_are_shuffled() -> None:
    data = {
        "standings": [
            {"rows": [
                _row(3, 103, "C", 49, group=1),
                _row(1, 201, "D", 35, group=2),
                _row(1, 101, "A", 59, group=1),
                _row(2, 202, "E", 32, group=2),
                _row(2, 102, "B", 57, group=1),
            ]}
        ]
    }
    rows = parse_standings(data)
    assert [r.competitor_id for r in rows] == [101, 102, 103, 201, 202]
    assert [r.position for r in rows] == [1, 2, 3, 4, 5]


def test_parse_standings_empty() -> None:
    assert parse_standings({}) == []
    assert parse_standings({"standings": []}) == []
    assert parse_standings({"standings": [{"rows": []}]}) == []

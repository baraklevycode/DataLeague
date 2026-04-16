"""Regression tests for the 365Scores recent-form parser.

The team power-ranking table was showing all-losses for every team after a
365Scores API change started returning ``outcome=-1`` for all competitors.
The parser now falls back to comparing scores (and finally to the
game-level ``winner`` flag) so the form stays correct even when
``outcome`` is unusable.
"""

from __future__ import annotations

from fetcher.clients.scores365 import parse_recent_form


def _game(home_id: int, home_score, away_id: int, away_score,
          home_outcome: int = -1, away_outcome: int = -1,
          winner: int | None = None) -> dict:
    return {
        "homeCompetitor": {"id": home_id, "score": home_score, "outcome": home_outcome},
        "awayCompetitor": {"id": away_id, "score": away_score, "outcome": away_outcome},
        "winner": winner,
    }


def test_parse_recent_form_uses_outcome_when_valid() -> None:
    games = [
        _game(1, 1.0, 2, 0.0, home_outcome=1, away_outcome=3),
        _game(3, 1.0, 2, 1.0, home_outcome=2, away_outcome=2),
    ]
    assert parse_recent_form(games, cid=2) == [0, 2]
    assert parse_recent_form(games, cid=1) == [1]
    assert parse_recent_form(games, cid=3) == [2]


def test_parse_recent_form_falls_back_to_scores_when_outcome_is_minus_one() -> None:
    """This is the observed broken-API case: outcome is -1 for everyone."""
    games = [
        _game(10, 1.0, 20, 3.0, home_outcome=-1, away_outcome=-1),
        _game(10, 2.0, 30, 0.0, home_outcome=-1, away_outcome=-1),
        _game(40, 1.0, 10, 1.0, home_outcome=-1, away_outcome=-1),
    ]
    assert parse_recent_form(games, cid=10) == [0, 1, 2]
    assert parse_recent_form(games, cid=20) == [1]
    assert parse_recent_form(games, cid=40) == [2]


def test_parse_recent_form_falls_back_to_game_winner_when_scores_missing() -> None:
    games = [
        _game(1, None, 2, None, home_outcome=-1, away_outcome=-1, winner=1),
        _game(2, None, 3, None, home_outcome=-1, away_outcome=-1, winner=2),
        _game(1, None, 4, None, home_outcome=-1, away_outcome=-1, winner=None),
    ]
    assert parse_recent_form(games, cid=1) == [1, 0]
    assert parse_recent_form(games, cid=2) == [0, 0]
    assert parse_recent_form(games, cid=3) == [1]
    assert parse_recent_form(games, cid=4) == [0]


def test_parse_recent_form_empty_or_none() -> None:
    assert parse_recent_form([], cid=1) == []
    assert parse_recent_form(None, cid=1) == []  # type: ignore[arg-type]

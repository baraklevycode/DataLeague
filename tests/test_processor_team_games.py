"""Regression tests for DataProcessor.build_teams() game aggregation.

These tests guard against the transferee contamination bug where a player who
moved mid-season had their previous-team gameStats copied into their current
team's games list in ``docs/data/teams.json``.

The fix: DataProcessor.build_teams() filters gameStats by ``playerTeamId``
against the current team's Sport5 id so only matches actually played for
the team are aggregated.
"""

from __future__ import annotations

from fetcher.config import get_team_by_internal_id
from fetcher.schemas import Sport5GameStat, Sport5PlayerDetail, Sport5RoundStat
from fetcher.services.matcher import MatchedPlayer
from fetcher.services.processor import DataProcessor


def _make_processor(
    matched_players: list[MatchedPlayer],
    sport5_details: dict[int, Sport5PlayerDetail],
) -> DataProcessor:
    """Build a DataProcessor with the minimum inputs required for build_teams()."""
    return DataProcessor(
        matched_players=matched_players,
        sport5_teams=[],
        sport5_details=sport5_details,
        fc_season_stats=[],
        fc_round_stats={},
        standings=[],
        fc_team_id_map={},
        s365_by_sport5={},
        unmatched_names=[],
    )


def test_build_teams_filters_out_transferee_previous_team_games() -> None:
    """A player currently on HHA whose gameStats include a match played for HBS
    must NOT cause that HBS match to appear in HHA's games list."""
    hha = get_team_by_internal_id(10)
    hbs = get_team_by_internal_id(1)
    assert hha is not None and hbs is not None

    transferee = MatchedPlayer(
        internal_id=9001,
        name_he="שחקן בדיקה",
        name_en="Test Transferee",
        team=hha,
        sport5_id=9001,
        sport5_team_id=hha.sport5_id,
    )

    detail = Sport5PlayerDetail(
        id=9001,
        name="Test Transferee",
        roundsStats=[
            Sport5RoundStat(roundId=111, totalPoints=0, statsData=""),
            Sport5RoundStat(roundId=112, totalPoints=0, statsData=""),
        ],
        gameStats=[
            Sport5GameStat(
                gameId=1,
                playerTeamId=hbs.sport5_id,
                points=0,
                statsData="",
                opponentId=132,
                opponentName="",
                roundId=111,
                homeScore=2,
                awayScore=4,
                isHome=False,
            ),
            Sport5GameStat(
                gameId=2,
                playerTeamId=hha.sport5_id,
                points=0,
                statsData="",
                opponentId=198,
                opponentName="",
                roundId=112,
                homeScore=1,
                awayScore=0,
                isHome=True,
            ),
        ],
    )

    processor = _make_processor([transferee], {9001: detail})
    teams = processor.build_teams()

    hha_team = next(t for t in teams if t["id"] == 10)
    hbs_team = next(t for t in teams if t["id"] == 1)

    assert len(hha_team["games"]) == 1, (
        "HHA should have exactly one game (the playerTeamId=HHA one); "
        "the earlier HBS match the player brought from his previous club "
        "must be filtered out."
    )
    game = hha_team["games"][0]
    assert game["round"] == 2
    assert game["isHome"] is True
    assert game["goalsFor"] == 1
    assert game["goalsAgainst"] == 0
    assert game["opponentId"] == 13

    assert hbs_team["games"] == [], (
        "HBS should have no games: the only player with HBS gameStats is "
        "registered under HHA, and HBS has no matched players of its own."
    )


def test_build_teams_filters_self_opponent_bug() -> None:
    """The "opponentId == team.id" case (Bug B from teams.json validation):
    a player currently on HTA whose gameStats include his previous club's
    match against HTA. The previous-team gameStat's opponentId equals HTA's
    id from his ex-club POV - if we kept that row, HTA's R1 would list HTA
    as its own opponent."""
    hta = get_team_by_internal_id(4)
    ks = get_team_by_internal_id(9)
    assert hta is not None and ks is not None

    transferee = MatchedPlayer(
        internal_id=9002,
        name_he="שחקן בדיקה",
        name_en="Test Transferee",
        team=hta,
        sport5_id=9002,
        sport5_team_id=hta.sport5_id,
    )

    detail = Sport5PlayerDetail(
        id=9002,
        name="Test Transferee",
        roundsStats=[Sport5RoundStat(roundId=111, totalPoints=0, statsData="")],
        gameStats=[
            Sport5GameStat(
                gameId=3,
                playerTeamId=ks.sport5_id,
                points=0,
                statsData="",
                opponentId=hta.sport5_id,
                opponentName="",
                roundId=111,
                homeScore=1,
                awayScore=2,
                isHome=False,
            ),
        ],
    )

    processor = _make_processor([transferee], {9002: detail})
    teams = processor.build_teams()

    hta_team = next(t for t in teams if t["id"] == 4)
    assert hta_team["games"] == [], (
        "HTA must not inherit its own previous match from a transferee; "
        "otherwise we get the ``opponentId == team.id`` (self-opponent) bug."
    )

    for t in teams:
        for g in t["games"]:
            assert g["opponentId"] != t["id"], (
                f"Team {t['id']} has a game listing itself as opponent: {g}"
            )


def test_build_teams_keeps_games_when_playerteamid_matches() -> None:
    """Sanity check: when ``playerTeamId`` matches the team's Sport5 id,
    the gameStat is kept and attributes are computed correctly."""
    mta = get_team_by_internal_id(3)
    hpt = get_team_by_internal_id(6)
    assert mta is not None and hpt is not None

    player = MatchedPlayer(
        internal_id=9003,
        name_he="שחקן בדיקה",
        name_en="Test Player",
        team=mta,
        sport5_id=9003,
        sport5_team_id=mta.sport5_id,
    )

    detail = Sport5PlayerDetail(
        id=9003,
        name="Test Player",
        roundsStats=[Sport5RoundStat(roundId=111, totalPoints=0, statsData="")],
        gameStats=[
            Sport5GameStat(
                gameId=4,
                playerTeamId=mta.sport5_id,
                points=0,
                statsData="",
                opponentId=hpt.sport5_id,
                opponentName="",
                roundId=111,
                homeScore=0,
                awayScore=4,
                isHome=False,
            ),
        ],
    )

    processor = _make_processor([player], {9003: detail})
    teams = processor.build_teams()

    mta_team = next(t for t in teams if t["id"] == 3)
    assert len(mta_team["games"]) == 1
    game = mta_team["games"][0]
    assert game["round"] == 1
    assert game["isHome"] is False
    assert game["goalsFor"] == 4
    assert game["goalsAgainst"] == 0
    assert game["opponentId"] == 6

"""Regression tests for DataProcessor.build_rounds() per-round teamId propagation.

These tests guard against the xG mis-attribution bug: when a player transfers
mid-season, their pre-transfer round xG was credited to their new club because
rounds.json did not carry the team the player actually played for in that round.

The fix: DataProcessor.build_rounds() now stores the FC row's teamId (translated
to our internal id) on each per-round ``footballCoIl`` entry so the frontend can
aggregate team xG by the correct team.
"""

from __future__ import annotations

from fetcher.config import TEAM_MAPPINGS, get_team_by_internal_id
from fetcher.schemas import Sport5PlayerDetail, Sport5RoundStat
from fetcher.services.matcher import MatchedPlayer
from fetcher.services.processor import DataProcessor


def _fc_team_id_map() -> dict[int, int]:
    return {tm.footballcoil_id: tm.internal_id for tm in TEAM_MAPPINGS}


def _make_processor(
    matched_players: list[MatchedPlayer],
    sport5_details: dict[int, Sport5PlayerDetail],
    fc_season_stats: list[dict],
    fc_round_stats: dict[int, list[dict]],
) -> DataProcessor:
    return DataProcessor(
        matched_players=matched_players,
        sport5_teams=[],
        sport5_details=sport5_details,
        fc_season_stats=fc_season_stats,
        fc_round_stats=fc_round_stats,
        standings=[],
        fc_team_id_map=_fc_team_id_map(),
        s365_by_sport5={},
        unmatched_names=[],
    )


def test_build_rounds_attaches_per_round_team_id_for_transferees() -> None:
    """A player transferred HBS -> HHA mid-season: their early-round FC data
    must carry HBS's internal id, late rounds must carry HHA's internal id."""
    hba = get_team_by_internal_id(1)  # Hapoel Be'er Sheva (FC id 4554)
    hha = get_team_by_internal_id(10)  # Hapoel Haifa (FC id 14316)
    assert hba is not None and hha is not None

    player = MatchedPlayer(
        internal_id=7001,
        name_he="שחקן בדיקה",
        name_en="Test Transferee",
        team=hha,
        sport5_id=7001,
        sport5_team_id=hha.sport5_id,
    )

    detail = Sport5PlayerDetail(
        id=7001,
        name="Test Transferee",
        roundsStats=[
            Sport5RoundStat(roundId=111, totalPoints=0, statsData=""),
            Sport5RoundStat(roundId=112, totalPoints=0, statsData=""),
        ],
    )

    fc_season_row = {
        "playerId": 42001,
        "teamId": hha.footballcoil_id,
        "Goal": 5,
        "totalMinutesPlayed": 1800,
        "appearances": 20,
    }

    fc_round_1 = {
        "playerId": 42001,
        "teamId": hba.footballcoil_id,
        "expectedGoals": 0.25,
        "Goal": 0,
        "Assist": 0,
        "OnTarget": 1,
        "AttemptonGoal": 2,
        "totalMinutesPlayed": 90,
    }
    fc_round_2 = {
        "playerId": 42001,
        "teamId": hha.footballcoil_id,
        "expectedGoals": 0.40,
        "Goal": 1,
        "Assist": 0,
        "OnTarget": 2,
        "AttemptonGoal": 3,
        "totalMinutesPlayed": 90,
    }

    s5_detail = detail.model_copy(update={})
    s5_detail.seasonStats = {
        "statsData": '{"Goals": {"Count": 5}, "MinutesPlayed": {"Count": 1800}, "OpenLineup": {"Count": 20}}',
        "points": 50,
    }

    processor = _make_processor(
        matched_players=[player],
        sport5_details={7001: s5_detail},
        fc_season_stats=[fc_season_row],
        fc_round_stats={1: [fc_round_1], 2: [fc_round_2]},
    )

    rounds = processor.build_rounds()["rounds"]
    entry_r1 = rounds["1"]["players"]["7001"]["footballCoIl"]
    entry_r2 = rounds["2"]["players"]["7001"]["footballCoIl"]

    assert entry_r1 is not None and entry_r2 is not None
    assert entry_r1["teamId"] == 1, (
        f"Round 1 FC data must carry HBS's internal id (1), got {entry_r1['teamId']}"
    )
    assert entry_r2["teamId"] == 10, (
        f"Round 2 FC data must carry HHA's internal id (10), got {entry_r2['teamId']}"
    )
    assert entry_r1["expectedGoals"] == 0.25
    assert entry_r2["expectedGoals"] == 0.40


def test_build_rounds_team_id_is_none_for_unknown_fc_team() -> None:
    """If the FC row's teamId doesn't map to any internal team, teamId is None
    so the frontend will fall back to the player's current team."""
    hha = get_team_by_internal_id(10)
    assert hha is not None

    player = MatchedPlayer(
        internal_id=7002,
        name_he="",
        name_en="Test Player",
        team=hha,
        sport5_id=7002,
        sport5_team_id=hha.sport5_id,
    )

    detail = Sport5PlayerDetail(
        id=7002,
        name="Test Player",
        roundsStats=[Sport5RoundStat(roundId=111, totalPoints=0, statsData="")],
        seasonStats={
            "statsData": '{"Goals": {"Count": 2}, "MinutesPlayed": {"Count": 900}, "OpenLineup": {"Count": 10}}',
            "points": 20,
        },
    )

    fc_season_row = {
        "playerId": 42002,
        "teamId": hha.footballcoil_id,
        "Goal": 2,
        "totalMinutesPlayed": 900,
        "appearances": 10,
    }
    fc_round = {
        "playerId": 42002,
        "teamId": 999999,
        "expectedGoals": 0.10,
        "Goal": 0,
        "Assist": 0,
        "OnTarget": 0,
        "AttemptonGoal": 1,
        "totalMinutesPlayed": 45,
    }

    processor = _make_processor(
        matched_players=[player],
        sport5_details={7002: detail},
        fc_season_stats=[fc_season_row],
        fc_round_stats={1: [fc_round]},
    )

    rounds = processor.build_rounds()["rounds"]
    entry = rounds["1"]["players"]["7002"]["footballCoIl"]
    assert entry is not None
    assert entry["teamId"] is None
    assert entry["expectedGoals"] == 0.10

"""Orchestrates all API fetchers, matching, processing, and JSON output."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from pathlib import Path

from fetcher.clients.footballcoil import FootballCoIlClient
from fetcher.clients.scores365 import Scores365Client
from fetcher.clients.sport5 import Sport5Client
from fetcher.config import TEAM_MAPPINGS, Settings
from fetcher.services.matcher import PlayerMatcher
from fetcher.services.processor import DataProcessor

logger = logging.getLogger(__name__)


async def run_pipeline(settings: Settings) -> None:
    """Run the full data fetching pipeline."""
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting data fetch from all sources...")

    async with (
        Sport5Client(settings) as sport5,
        FootballCoIlClient(settings) as fc,
        Scores365Client(settings) as s365,
    ):
        # Fetch Sport5 teams and players
        logger.info("Fetching Sport5 teams and players...")
        sport5_teams_raw = await sport5.get_teams_and_players()

        all_player_ids: list[int] = []
        sport5_players_flat: list[dict] = []
        sport5_teams_dicts: list[dict] = []
        for team in sport5_teams_raw:
            td = {"id": team.id, "name": team.name, "logoPath": team.teamLogoPath, "shirtPath": team.teamShirtPath, "players": []}
            for p in team.players:
                all_player_ids.append(p.id)
                pd = p.model_dump()
                sport5_players_flat.append(pd)
                td["players"].append(pd)
            sport5_teams_dicts.append(td)

        logger.info("Found %d Sport5 players across %d teams", len(all_player_ids), len(sport5_teams_raw))

        # Parallel fetch
        logger.info("Fetching detailed data in parallel...")
        sport5_details, fc_players, fc_season, fc_rounds, standings, s365_games = await asyncio.gather(
            sport5.get_all_player_details(all_player_ids),
            fc.get_players(),
            fc.get_season_stats(),
            fc.get_all_round_stats(),
            s365.get_standings(),
            s365.get_completed_games(),
        )

        # Fetch 365Scores game details for xA data
        logger.info("Fetching %d game details from 365Scores...", len(s365_games))
        s365_game_data = await s365.get_all_game_details(s365_games)

    # Build FC teamId -> internal team mapping by correlating standings data
    fc_team_id_map = _build_fc_team_map(fc_season, standings, sport5_details, sport5_teams_dicts)
    logger.info("Mapped %d FC team IDs to internal teams", len(fc_team_id_map))

    # Match players
    logger.info("Matching players...")
    fc_player_dicts = [
        {
            "_id": p.id,
            "name": p.name,
            "hebrewName": p.hebrewName,
            "position": p.position,
            "teamName": p.teamName,
        }
        for p in fc_players
    ]

    matcher = PlayerMatcher(
        sport5_players=sport5_players_flat,
        footballcoil_players=fc_player_dicts,
        scores365_players=[],  # 365Scores game details don't return player data
    )
    matched = matcher.match_all()

    # Process
    logger.info("Processing data into output JSON...")
    processor = DataProcessor(
        matched_players=matched,
        sport5_teams=sport5_teams_dicts,
        sport5_details=sport5_details,
        fc_season_stats=fc_season,
        fc_round_stats=fc_rounds,
        standings=standings,
        fc_team_id_map=fc_team_id_map,
        s365_game_data=s365_game_data,
        unmatched_names=[],
    )

    players = processor.build_players()
    teams = processor.build_teams()
    rounds = processor.build_rounds()
    leaders = processor.build_leaders(players)
    meta = processor.build_meta(players)

    # Write JSON files
    _write_json(output_dir / "players.json", {"players": players})
    _write_json(output_dir / "teams.json", {"teams": teams})
    _write_json(output_dir / "rounds.json", rounds)
    _write_json(output_dir / "leaders.json", leaders)
    _write_json(output_dir / "meta.json", meta)

    logger.info("Pipeline complete! Output written to %s", output_dir)
    logger.info(
        "Summary: %d players, %d FC-matched, %d teams, %d rounds",
        len(players),
        meta["matchedPlayers"],
        len(teams),
        meta["currentRound"],
    )


def _build_fc_team_map(
    fc_stats: list[dict],
    standings: list,
    sport5_details: dict | None = None,
    sport5_teams: list[dict] | None = None,
) -> dict[int, int]:
    """Map Football.co.il teamIds to internal team IDs.

    Uses top-scorer fingerprinting: for each Sport5 team, find the top scorer's
    goals+minutes, then find the FC team whose top scorer has matching stats.
    """
    from fetcher.clients.sport5 import Sport5Client

    # Group FC stats by teamId
    fc_by_team: dict[int, list[dict]] = defaultdict(list)
    fc_team_count: dict[int, int] = defaultdict(int)
    for row in fc_stats:
        fc_tid = row.get("teamId", -1)
        if fc_tid != -1:
            fc_by_team[fc_tid].append(row)
            fc_team_count[fc_tid] += 1

    # Only consider FC teams with 20+ players
    fc_teams = {tid: rows for tid, rows in fc_by_team.items() if fc_team_count[tid] >= 20}

    # Build Sport5 top scorer per internal team
    s5_team_top: dict[int, tuple[int, int]] = {}  # internal_id -> (goals, minutes)
    if sport5_details and sport5_teams:
        from fetcher.config import build_sport5_id_map
        s5_map = build_sport5_id_map()
        for team_dict in sport5_teams:
            tm = s5_map.get(team_dict["id"])
            if not tm:
                continue
            best_goals = 0
            best_mins = 0
            for p in team_dict.get("players", []):
                detail = sport5_details.get(p["id"])
                if not detail or not detail.seasonStats:
                    continue
                sd = Sport5Client.parse_stats_data(detail.seasonStats.get("statsData", ""))
                if sd.Goals.Count > best_goals or (sd.Goals.Count == best_goals and sd.MinutesPlayed.Count > best_mins):
                    best_goals = sd.Goals.Count
                    best_mins = sd.MinutesPlayed.Count
            if best_goals > 0:
                s5_team_top[tm.internal_id] = (best_goals, best_mins)

    # For each FC team, compute top scorer fingerprint
    fc_team_top: dict[int, tuple[int, int]] = {}
    for fc_tid, rows in fc_teams.items():
        best = max(rows, key=lambda r: (int(r.get("Goal", 0)), int(r.get("totalMinutesPlayed", 0))))
        fc_team_top[fc_tid] = (int(best.get("Goal", 0)), int(best.get("totalMinutesPlayed", 0)))

    # Match: for each internal team, find the FC team whose top scorer
    # best matches by goals (exact or ±1) and minutes (within 15%)
    result: dict[int, int] = {}
    used_fc: set[int] = set()

    pairs: list[tuple[float, int, int]] = []
    for int_id, (s5_goals, s5_mins) in s5_team_top.items():
        for fc_tid, (fc_goals, fc_mins) in fc_team_top.items():
            goal_diff = abs(s5_goals - fc_goals)
            min_pct = abs(s5_mins - fc_mins) / max(s5_mins, 1)
            if goal_diff <= 2 and min_pct < 0.15:
                score = goal_diff * 100 + min_pct * 50
                pairs.append((score, fc_tid, int_id))

    pairs.sort()
    used_internal: set[int] = set()
    for score, fc_tid, int_id in pairs:
        if fc_tid in used_fc or int_id in used_internal:
            continue
        result[fc_tid] = int_id
        used_fc.add(fc_tid)
        used_internal.add(int_id)

    return result


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", path)

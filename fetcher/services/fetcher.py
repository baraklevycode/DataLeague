"""Orchestrates all API fetchers, matching, processing, and JSON output."""

from __future__ import annotations

import asyncio
import json
import logging
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
    fc_team_id_map = _build_fc_team_map()
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


def _build_fc_team_map() -> dict[int, int]:
    """Map Football.co.il teamIds to internal team IDs.

    Uses hardcoded IDs confirmed from the FC /team API endpoint.
    """
    from fetcher.config import build_footballcoil_id_map
    return build_footballcoil_id_map()


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Wrote %s", path)

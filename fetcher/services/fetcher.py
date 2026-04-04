"""Orchestrates all API fetchers, matching, processing, and JSON output."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from fetcher.clients.footballcoil import FootballCoIlClient
from fetcher.clients.scores365 import Scores365Client
from fetcher.clients.sport5 import Sport5Client
from fetcher.config import Settings
from fetcher.services.matcher import PlayerMatcher
from fetcher.services.processor import DataProcessor

logger = logging.getLogger(__name__)

CACHE_DIR = Path("docs/data/.cache")


def _load_cache(name: str) -> dict | list | None:
    path = CACHE_DIR / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _save_cache(name: str, data: object) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / f"{name}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


async def run_pipeline(settings: Settings) -> None:
    """Run the full data fetching pipeline."""
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    logger.info("Starting data fetch...")

    async with (
        Sport5Client(settings) as sport5,
        FootballCoIlClient(settings) as fc,
        Scores365Client(settings) as s365,
    ):
        # Sport5 teams (fast, always fresh)
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

        logger.info("Found %d players across %d teams (%.1fs)", len(all_player_ids), len(sport5_teams_raw), time.time() - t0)

        # Parallel: Sport5 details + FC + 365 standings
        t1 = time.time()
        sport5_details, fc_players, fc_season, fc_rounds, standings = await asyncio.gather(
            sport5.get_all_player_details(all_player_ids),
            fc.get_players(),
            fc.get_season_stats(),
            fc.get_all_round_stats(),
            s365.get_standings(),
        )
        logger.info("Fetched Sport5+FC+standings (%.1fs)", time.time() - t1)

        # 365Scores: smart multi-strategy search
        t2 = time.time()
        played_ids = {pid for pid, detail in sport5_details.items() if detail.roundsStats}

        # Build FC English name lookup
        fc_english = {p.hebrewName: p.name for p in fc_players if p.name}

        # Build sport5_id -> 365 team ID lookup
        from fetcher.config import build_sport5_id_map
        s5_team_map = build_sport5_id_map()

        # Prepare search list: (sport5_id, hebrew_name, english_name, 365_team_id)
        search_list: list[tuple[int, str, str, int]] = []
        for p in sport5_players_flat:
            if p["id"] not in played_ids:
                continue
            he_name = p["name"]
            en_name = fc_english.get(he_name, "")
            tm = s5_team_map.get(p["teamId"])
            club_id = tm.scores365_id if tm else 0
            search_list.append((p["id"], he_name, en_name, club_id))

        s365_id_map = await s365.resolve_all_players(search_list)

        athlete_ids = list(s365_id_map.values())
        s365_stats = await s365.get_all_athletes_stats(athlete_ids)
        logger.info("365Scores: %d athletes resolved, %d with stats (%.1fs)", len(s365_id_map), len(s365_stats), time.time() - t2)

    # Build sport5_id -> 365 stats
    s365_by_sport5: dict[int, dict] = {}
    for sport5_id, athlete_id in s365_id_map.items():
        if athlete_id in s365_stats:
            s365_by_sport5[sport5_id] = s365_stats[athlete_id]

    # FC team mapping
    fc_team_id_map = _build_fc_team_map()

    # Match players
    fc_player_dicts = [
        {"_id": p.id, "name": p.name, "hebrewName": p.hebrewName, "position": p.position, "teamName": p.teamName}
        for p in fc_players
    ]
    matcher = PlayerMatcher(
        sport5_players=sport5_players_flat,
        footballcoil_players=fc_player_dicts,
        scores365_players=[],
    )
    matched = matcher.match_all()

    # Process
    processor = DataProcessor(
        matched_players=matched,
        sport5_teams=sport5_teams_dicts,
        sport5_details=sport5_details,
        fc_season_stats=fc_season,
        fc_round_stats=fc_rounds,
        standings=standings,
        fc_team_id_map=fc_team_id_map,
        s365_by_sport5=s365_by_sport5,
        unmatched_names=[],
    )

    teams = processor.build_teams()  # must run first — builds difficulty lookup for players
    players = processor.build_players()
    rounds = processor.build_rounds()
    leaders = processor.build_leaders(players)
    meta = processor.build_meta(players)

    _write_json(output_dir / "players.json", {"players": players})
    _write_json(output_dir / "teams.json", {"teams": teams})
    _write_json(output_dir / "rounds.json", rounds)
    _write_json(output_dir / "leaders.json", leaders)
    _write_json(output_dir / "meta.json", meta)

    elapsed = time.time() - t0
    logger.info(
        "Done in %.0fs! %d players, %d FC-matched, %d 365-matched, %d teams, %d rounds",
        elapsed, len(players), meta["matchedPlayers"], len(s365_by_sport5), len(teams), meta["currentRound"],
    )


def _build_fc_team_map() -> dict[int, int]:
    from fetcher.config import build_footballcoil_id_map
    return build_footballcoil_id_map()


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

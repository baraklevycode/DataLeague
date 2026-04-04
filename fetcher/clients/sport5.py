"""Sport5 Dream Team API client."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from fetcher.config import Settings
from fetcher.schemas import Sport5Player, Sport5PlayerDetail, Sport5RoundStat, Sport5StatsData, Sport5Team

logger = logging.getLogger(__name__)


class Sport5Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = settings.sport5_base_url
        self.season_id = settings.sport5_season_id
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Sport5Client:
        self._client = httpx.AsyncClient(timeout=30.0, limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
        await self._login()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _login(self) -> None:
        resp = await self._client.post(
            f"{self.base}/Account/Login",
            json={
                "email": self.settings.sport5_email,
                "password": self.settings.sport5_password,
            },
        )
        resp.raise_for_status()
        logger.info("Sport5 login successful")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_teams_and_players(self) -> list[Sport5Team]:
        resp = await self._client.get(
            f"{self.base}/Players/GetTeamsAndPlayers",
            params={"seasonId": self.season_id},
        )
        resp.raise_for_status()
        raw = resp.json()
        data = raw.get("data", raw) if isinstance(raw, dict) else raw
        teams: list[Sport5Team] = []
        for team_data in data:
            players = [Sport5Player.model_validate(p) for p in team_data.get("players", [])]
            team = Sport5Team(
                id=team_data["id"],
                name=team_data.get("name", ""),
                teamLogoPath=team_data.get("teamLogoPath", ""),
                teamShirtPath=team_data.get("teamShirtPath", ""),
                players=players,
            )
            teams.append(team)
        return teams

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_player_detail(self, player_id: int) -> Sport5PlayerDetail:
        resp = await self._client.get(
            f"{self.base}/Players/GetPlayerData",
            params={"playerId": player_id, "seasonId": self.season_id},
        )
        resp.raise_for_status()
        raw = resp.json()
        data = raw.get("data", raw) if isinstance(raw, dict) else raw

        # Parse roundsStats
        rounds_stats: list[Sport5RoundStat] = []
        for rs in data.get("roundsStats", []):
            rounds_stats.append(Sport5RoundStat(
                roundId=rs.get("roundId", 0),
                totalPoints=rs.get("points", 0),
                statsData=rs.get("statsData", ""),
            ))

        return Sport5PlayerDetail(
            id=player_id,
            name=data.get("player", {}).get("name", "") if isinstance(data.get("player"), dict) else "",
            seasonStats=data.get("seasonStats"),
            roundsStats=rounds_stats,
            timesSelected=data.get("timesSelected", 0),
            avgPoints=data.get("avgPoints", 0.0),
        )

    async def get_all_player_details(
        self, player_ids: list[int]
    ) -> dict[int, Sport5PlayerDetail]:
        sem = asyncio.Semaphore(self.settings.sport5_max_concurrent)
        results: dict[int, Sport5PlayerDetail] = {}

        async def _fetch(pid: int) -> None:
            async with sem:
                try:
                    detail = await self.get_player_detail(pid)
                    results[pid] = detail
                except Exception:
                    logger.warning("Failed to fetch Sport5 player %d", pid)

        tasks = [asyncio.create_task(_fetch(pid)) for pid in player_ids]
        await asyncio.gather(*tasks)
        logger.info("Fetched %d/%d Sport5 player details", len(results), len(player_ids))
        return results

    @staticmethod
    def parse_stats_data(stats_data_str: str) -> Sport5StatsData:
        """Double-parse the statsData JSON string."""
        if not stats_data_str:
            return Sport5StatsData()
        try:
            parsed = json.loads(stats_data_str)
            if isinstance(parsed, str):
                parsed = json.loads(parsed)
            return Sport5StatsData.model_validate(parsed)
        except (json.JSONDecodeError, Exception):
            logger.warning("Failed to parse statsData")
            return Sport5StatsData()

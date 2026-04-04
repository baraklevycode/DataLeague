"""Sport5 Dream Team API client."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from fetcher.config import Settings
from fetcher.schemas import Sport5GameStat, Sport5Player, Sport5PlayerDetail, Sport5RoundStat, Sport5StatsData, Sport5Team

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

        # Parse gameStats with opponent info
        game_stats: list[Sport5GameStat] = []
        for gs in data.get("gameStats", []):
            game = gs.get("game", {})
            player_team = gs.get("playerTeamId", 0)
            team_a = game.get("teamAId", 0)
            team_b = game.get("teamBId", 0)
            is_home = player_team == team_a
            opponent_id = team_b if is_home else team_a
            opponent_name = game.get("teamBName", "") if is_home else game.get("teamAName", "")

            result_str = game.get("resultData", "")
            home_score = away_score = 0
            if result_str:
                try:
                    rd = json.loads(result_str)
                    home_score = rd.get("HostGoals", 0)
                    away_score = rd.get("GuestGoals", 0)
                except (json.JSONDecodeError, Exception):
                    pass

            game_stats.append(Sport5GameStat(
                gameId=gs.get("gameId", 0),
                playerTeamId=player_team,
                points=gs.get("points", 0),
                statsData=gs.get("statsData", ""),
                opponentId=opponent_id,
                opponentName=opponent_name,
                roundId=game.get("roundId", 0),
                homeScore=home_score,
                awayScore=away_score,
                isHome=is_home,
            ))

        # Parse futureGames
        future_games: list[dict] = []
        for fg in data.get("futureGames", []):
            future_games.append({
                "roundId": fg.get("roundId", 0),
                "teamAId": fg.get("teamAId", 0),
                "teamBId": fg.get("teamBId", 0),
                "teamAName": fg.get("teamAName", ""),
                "teamBName": fg.get("teamBName", ""),
            })

        return Sport5PlayerDetail(
            id=player_id,
            name=data.get("player", {}).get("name", "") if isinstance(data.get("player"), dict) else "",
            seasonStats=data.get("seasonStats"),
            roundsStats=rounds_stats,
            gameStats=game_stats,
            futureGames=future_games,
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

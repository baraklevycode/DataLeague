"""Football.co.il (Bamboo Cloud) API client."""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from fetcher.config import Settings
from fetcher.schemas import FootballCoIlPlayer

logger = logging.getLogger(__name__)

# Stage names and their round ranges for overall round mapping
STAGES = [
    ("RegularSeason", 1, 26, 0),       # rounds 1-26 → overall 1-26
    ("ChampionshipRound", 1, 7, 26),    # rounds 1-7  → overall 27-33
    ("RelegationRound", 1, 7, 26),      # rounds 1-7  → overall 27-33
]


def _unwrap(raw: dict | list) -> dict | list:
    """Unwrap Bamboo Cloud {data: ..., meta: ...} envelope."""
    if isinstance(raw, dict) and "data" in raw:
        return raw["data"]
    return raw


class FootballCoIlClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = settings.footballcoil_base_url
        self.tournament_id = settings.footballcoil_tournament_id
        self.season = settings.footballcoil_season
        self.common_params = {
            "format": "json",
            "iid": settings.footballcoil_iid,
            "returnZeros": "false",
            "disableDefaultFilter": "true",
            "useCache": "false",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> FootballCoIlClient:
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    def _filter(self, **extra: object) -> str:
        f: dict = {"tournamentId": self.tournament_id, "seasonName": self.season}
        f.update(extra)
        return json.dumps(f)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_players(self) -> list[FootballCoIlPlayer]:
        resp = await self._client.get(
            f"{self.base}/player",
            params={
                **self.common_params,
                "expand": json.dumps(["instatId", "teamInstatId"]),
                "filter": self._filter(),
            },
        )
        resp.raise_for_status()
        raw = _unwrap(resp.json())

        # Response is a dict keyed by player numeric ID
        items = raw.values() if isinstance(raw, dict) else raw
        players: list[FootballCoIlPlayer] = []
        for item in items:
            try:
                # Extract numeric id from the item
                pid = item.get("id", 0) or 0
                # Get current team from clubs list
                team_name = ""
                for club in item.get("clubs", []):
                    if club.get("seasonName") == self.season:
                        team_name = club.get("tournamentName", "")
                        break

                p = FootballCoIlPlayer(
                    _id=pid,
                    name=item.get("name", ""),
                    hebrewName=item.get("hebrewName", ""),
                    position=item.get("position", ""),
                    teamName=team_name,
                    teamId=item.get("teamId"),
                    instatId=int(item["instatId"]) if item.get("instatId") else None,
                )
                players.append(p)
            except Exception:
                logger.warning("Failed to parse football.co.il player: %s", item.get("name", "?"))
        logger.info("Fetched %d football.co.il players", len(players))
        return players

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_season_stats(self) -> list[dict]:
        resp = await self._client.get(
            f"{self.base}/stats",
            params={
                **self.common_params,
                "filter": self._filter(round=0),
            },
        )
        resp.raise_for_status()
        raw = _unwrap(resp.json())
        # raw is dict keyed by composite IDs — convert to list, filter to player rows
        if isinstance(raw, dict):
            return [v for v in raw.values() if v.get("playerId", -1) != -1]
        return raw

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_round_stats(self, stage: str, round_num: int) -> list[dict]:
        resp = await self._client.get(
            f"{self.base}/stats",
            params={
                **self.common_params,
                "filter": self._filter(round=round_num, stage=stage),
            },
        )
        resp.raise_for_status()
        raw = _unwrap(resp.json())
        if isinstance(raw, dict):
            return [v for v in raw.values() if v.get("playerId", -1) != -1]
        return raw

    async def get_all_round_stats(self) -> dict[int, list[dict]]:
        """Fetch round stats for all stages/rounds. Returns {overall_round: stats_list}."""
        results: dict[int, list[dict]] = {}

        async def _fetch(stage: str, rnd: int, overall: int) -> None:
            try:
                stats = await self.get_round_stats(stage, rnd)
                if stats:
                    results[overall] = stats
            except Exception:
                logger.warning("Failed to fetch football.co.il %s round %d", stage, rnd)

        tasks = []
        for stage_name, start, end, offset in STAGES:
            for rnd in range(start, end + 1):
                overall = rnd + offset
                tasks.append(asyncio.create_task(_fetch(stage_name, rnd, overall)))

        await asyncio.gather(*tasks)
        logger.info("Fetched football.co.il stats for %d rounds", len(results))
        return results

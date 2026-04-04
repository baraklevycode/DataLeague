"""365Scores API client."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from fetcher.config import Settings
from fetcher.schemas import Scores365GameRef, Scores365StandingRow

logger = logging.getLogger(__name__)

# highlightStats type IDs → field names
HIGHLIGHT_STAT_TYPES = {
    205: "xG",
    207: "xA",
    54: "rating",
    5: "appearances",
    1: "goals",
    2: "assists",
    223: "totalShots",
    35: "shotsOnTarget",
    34: "shotsOffTarget",
    212: "bigChancesCreated",
    210: "bigChancesMissed",
    44: "touches",
    222: "minutesPlayed",
    3: "yellowCards",
    4: "redCards",
}


def _parse_stat_value(val: str | float | int) -> float:
    """Parse stat value like '12(3פנ׳)', '22/24', '7.5', '90'' to float."""
    if isinstance(val, (int, float)):
        return float(val)
    if not val or not isinstance(val, str):
        return 0.0
    # Handle "12(3פנ׳)" → 12
    cleaned = re.sub(r"\(.*?\)", "", val)
    # Handle "22/24" → 22
    if "/" in cleaned:
        cleaned = cleaned.split("/")[0]
    # Remove non-numeric except dots
    cleaned = re.sub(r"[^0-9.]", "", cleaned)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


class Scores365Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = settings.scores365_base_url
        self.competition_id = settings.scores365_competition_id
        self.common_params = {
            "appTypeId": "5",
            "langId": "2",
            "timezoneName": "Asia/Jerusalem",
            "userCountryId": "6",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Scores365Client:
        self._client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=50),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://www.365scores.com/",
            },
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_standings(self) -> list[Scores365StandingRow]:
        resp = await self._client.get(
            f"{self.base}/standings/",
            params={**self.common_params, "competitions": self.competition_id},
        )
        resp.raise_for_status()
        data = resp.json()

        rows: list[Scores365StandingRow] = []
        for comp in data.get("standings", []):
            for row in comp.get("rows", []):
                competitor = row.get("competitor", {})
                form: list[int] = []
                for f in row.get("detailedRecentForm", []):
                    home = f.get("homeCompetitor", {})
                    away = f.get("awayCompetitor", {})
                    cid = competitor.get("id", 0)
                    if home.get("id") == cid:
                        outcome = home.get("outcome", 0)
                    else:
                        outcome = away.get("outcome", 0)
                    form.append({1: 1, 2: 2, 3: 0}.get(outcome, 0))

                rows.append(Scores365StandingRow(
                    competitor_id=competitor.get("id", 0),
                    competitor_name=competitor.get("name", ""),
                    position=row.get("position", 0),
                    played=row.get("gamePlayed", 0),
                    won=row.get("gamesWon", 0),
                    drawn=row.get("gamesEven", 0),
                    lost=row.get("gamesLost", 0),
                    goals_for=row.get("for", 0),
                    goals_against=row.get("against", 0),
                    points=int(row.get("points", 0)),
                    recent_form=form[-5:] if form else [],
                ))
        logger.info("Fetched standings for %d teams", len(rows))
        return rows

    # ------------------------------------------------------------------
    # Player identification via search
    # ------------------------------------------------------------------

    async def search_player(self, name: str) -> dict | None:
        """Search for a player by name. Returns {id, name, clubId} or None."""
        try:
            resp = await self._client.get(
                f"{self.base}/search/",
                params={**self.common_params, "query": name, "entityTypes": "3"},
            )
            if resp.status_code != 200:
                return None
            athletes = resp.json().get("athletes", [])
            return athletes[0] if athletes else None
        except Exception:
            return None

    async def resolve_all_players(
        self, player_names: list[tuple[int, str]], cache_path: str = "docs/data/.365cache.json"
    ) -> dict[int, int]:
        """Search for all players by name. Uses local cache to avoid re-searching.
        Returns {sport5_id: athlete_id}."""
        import json
        from pathlib import Path

        # Load cache
        cache_file = Path(cache_path)
        cache: dict[str, int] = {}
        if cache_file.exists():
            try:
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        results: dict[int, int] = {}
        to_search: list[tuple[int, str]] = []

        for s5id, name in player_names:
            cached = cache.get(str(s5id))
            if cached:
                results[s5id] = cached
            else:
                to_search.append((s5id, name))

        if to_search:
            logger.info("Searching 365Scores for %d new players (%d cached)...", len(to_search), len(results))
            sem = asyncio.Semaphore(50)

            async def _search(sport5_id: int, name: str) -> None:
                async with sem:
                    athlete = await self.search_player(name)
                    if athlete and athlete.get("id"):
                        results[sport5_id] = athlete["id"]
                        cache[str(sport5_id)] = athlete["id"]

            tasks = [asyncio.create_task(_search(s5id, name)) for s5id, name in to_search]
            await asyncio.gather(*tasks)

            # Save cache
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(cache), encoding="utf-8")

        logger.info("Resolved %d/%d players via 365Scores (%d from cache)", len(results), len(player_names), len(results) - len(to_search) + len([s for s in to_search if str(s[0]) in cache]))
        return results

    # ------------------------------------------------------------------
    # Full player stats via athletes endpoint
    # ------------------------------------------------------------------

    async def _fetch_athlete_batch(self, athlete_ids: list[int]) -> dict[int, dict]:
        """Fetch full stats for a small batch of athletes."""
        if not athlete_ids:
            return {}

        batch = ",".join(str(x) for x in athlete_ids)
        resp = await self._client.get(
            f"{self.base}/athletes/",
            params={
                **self.common_params,
                "athletes": batch,
                "competitionId": self.competition_id,
                "fullDetails": "true",
                "topBookmaker": "1",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results: dict[int, dict] = {}
        for athlete in data.get("athletes", []):
            aid = athlete.get("id", 0)
            if not aid:
                continue

            stats: dict[str, float] = {}
            for comp_stats in athlete.get("highlightStats", []):
                if comp_stats.get("competitionId") == self.competition_id:
                    for s in comp_stats.get("stats", []):
                        stat_type = s.get("type", 0)
                        field_name = HIGHLIGHT_STAT_TYPES.get(stat_type)
                        if field_name:
                            stats[field_name] = _parse_stat_value(s.get("value", 0))

            if stats:
                results[aid] = stats

        return results

    async def get_all_athletes_stats(
        self, athlete_ids: list[int]
    ) -> dict[int, dict]:
        """Fetch full stats for all athletes — parallel batches of 5, no retries."""
        all_results: dict[int, dict] = {}
        sem = asyncio.Semaphore(10)
        batch_size = 5

        async def _fetch(batch: list[int]) -> None:
            async with sem:
                try:
                    results = await self._fetch_athlete_batch(batch)
                    all_results.update(results)
                except Exception:
                    pass  # skip failed batches silently

        tasks = []
        for i in range(0, len(athlete_ids), batch_size):
            tasks.append(asyncio.create_task(_fetch(athlete_ids[i:i + batch_size])))
        await asyncio.gather(*tasks)

        logger.info("Fetched 365Scores stats for %d/%d athletes", len(all_results), len(athlete_ids))
        return all_results

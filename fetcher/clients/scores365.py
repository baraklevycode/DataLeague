"""365Scores API client."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from fetcher.config import Settings
from fetcher.schemas import Scores365GameRef, Scores365PlayerGameStats, Scores365StandingRow

logger = logging.getLogger(__name__)

# Stat name mapping — API returns names in French/Hebrew depending on game
STAT_NAME_MAP = {
    # French names (most common)
    "Buts": "goals",
    "Pass. Décisiv.": "assists",
    "Passes décisives": "assists",
    "Buts attendus": "xG",
    "Passe décisive attendue": "xA",
    "Minutes": "minutes",
    "Tirs cadrés": "shotsOnTarget",
    "Tirs au total": "totalShots",
    "Tirs non cadrés": "shotsOffTarget",
    "Passes Completed": "passesCompleted",
    "Touches": "touches",
    "Tacles Gagnés": "tacklesWon",
    "Les interceptions": "interceptions",
    "Dégagements": "clearances",
    "Duels aériens gagnés": "aerialDuelsWon",
    "Duels au sol gagnés": "groundDuelsWon",
    "Dribbles réussis": "dribblesWon",
    "Perte de balle": "ballLosses",
    "Fautes faites": "fouls",
    "Gardien Parades": "saves",
    "Buts encaissés": "goalsConceded",
    "Tirs bloqués": "blocks",
    "Grosses occasions": "bigChancesCreated",
    "De grandes occasions manquées": "bigChancesMissed",
    "Hors jeu": "offsides",
    # Hebrew names (some games)
    "שערים": "goals",
    "בישולים": "assists",
    "שערים צפויים": "xG",
    "בישולים צפויים": "xA",
    "דקות": "minutes",
    "בעיטות למסגרת": "shotsOnTarget",
    "נגיעות בכדור": "touches",
    "תיקולים מוצלחים": "tacklesWon",
    "חטיפות": "interceptions",
    "דריבלים מוצלחים": "dribblesWon",
    "הצלות שוער": "saves",
    "ספיגת שערים": "goalsConceded",
}


def _parse_minutes(val: str | float | int) -> int:
    """Parse minutes value like \"90'\" or 90 to int."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        cleaned = re.sub(r"[^0-9]", "", val)
        return int(cleaned) if cleaned else 0
    return 0


class Scores365Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base = settings.scores365_base_url
        self.competition_id = settings.scores365_competition_id
        self.common_params = {
            "appTypeId": "5",
            "langId": "15",
            "timezoneName": "Asia/Jerusalem",
            "userCountryId": "2",
        }
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> Scores365Client:
        self._client = httpx.AsyncClient(timeout=30.0)
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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_completed_games(self) -> list[Scores365GameRef]:
        resp = await self._client.get(
            f"{self.base}/games/results/",
            params={**self.common_params, "competitions": self.competition_id},
        )
        resp.raise_for_status()
        data = resp.json()

        games: list[Scores365GameRef] = []
        for game in data.get("games", []):
            home = game.get("homeCompetitor", {})
            away = game.get("awayCompetitor", {})
            games.append(Scores365GameRef(
                game_id=game["id"],
                round_num=game.get("roundNum", 0),
                home_team_id=home.get("id", 0),
                away_team_id=away.get("id", 0),
                home_score=int(home.get("score", 0)),
                away_score=int(away.get("score", 0)),
            ))
        logger.info("Fetched %d completed games", len(games))
        return games

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def get_game_detail(self, game_id: int) -> tuple[int, list[Scores365PlayerGameStats]]:
        """Returns (round_num, player_stats) with anonymous players (no IDs/names)."""
        resp = await self._client.get(
            f"{self.base}/game/",
            params={**self.common_params, "gameId": game_id},
        )
        resp.raise_for_status()
        data = resp.json()

        game = data.get("game", {})
        round_num = game.get("roundNum", 0)
        player_stats: list[Scores365PlayerGameStats] = []

        for side in ("homeCompetitor", "awayCompetitor"):
            competitor = game.get(side, {})
            team_id = competitor.get("id", 0)
            members = competitor.get("lineups", {}).get("members", [])

            for idx, member in enumerate(members):
                # Parse stats from Hebrew names to English keys
                stats_dict: dict[str, float] = {}
                for stat in member.get("stats", []):
                    he_name = stat.get("name", "")
                    en_name = STAT_NAME_MAP.get(he_name, "")
                    if en_name:
                        raw_val = stat.get("value", 0)
                        if en_name == "minutes":
                            stats_dict[en_name] = float(_parse_minutes(raw_val))
                        else:
                            try:
                                stats_dict[en_name] = float(raw_val)
                            except (ValueError, TypeError):
                                pass

                pos = member.get("position", {})
                pos_id = pos.get("id", 0) if isinstance(pos, dict) else 0

                player_stats.append(Scores365PlayerGameStats(
                    player_id=0,  # anonymous
                    player_name="",
                    team_id=team_id,
                    stats=stats_dict,
                    rating=0.0,
                ))

        return round_num, player_stats

    async def get_all_game_details(
        self, games: list[Scores365GameRef]
    ) -> dict[int, list[tuple[int, list[Scores365PlayerGameStats]]]]:
        """Fetch all game details. Returns {round_num: [(game_id, [player_stats])]}."""
        sem = asyncio.Semaphore(self.settings.scores365_max_concurrent)
        results: dict[int, list[tuple[int, list[Scores365PlayerGameStats]]]] = {}

        async def _fetch(game: Scores365GameRef) -> None:
            async with sem:
                try:
                    round_num, stats = await self.get_game_detail(game.game_id)
                    results.setdefault(round_num, []).append((game.game_id, stats))
                except Exception:
                    logger.warning("Failed to fetch 365Scores game %d", game.game_id)

        tasks = [asyncio.create_task(_fetch(g)) for g in games]
        await asyncio.gather(*tasks)
        logger.info("Fetched details for %d games across %d rounds", len(games), len(results))
        return results

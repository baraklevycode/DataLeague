"""MarathonBet Playwright scraper — clean sheet odds from 'Team to Score' markets."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

BASE_URL = "https://www.marathonbet.com"
LEAGUE_URL = "https://www.marathonbet.com/en/betting/Football/Israel/Premier+League+-+345450"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class MarathonGame:
    homeTeam: str
    awayTeam: str
    gameId: str
    homeCleanSheetPct: float | None
    awayCleanSheetPct: float | None
    noData: bool


class MarathonBetClient:
    """Playwright scraper for MarathonBet Israeli Premier League clean sheet odds."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None

    async def __aenter__(self) -> "MarathonBetClient":
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        logger.info("MarathonBet browser launched")
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _new_page(self):
        page = await self._browser.new_page()
        await page.set_extra_http_headers({"User-Agent": _UA})
        return page

    async def scrape_all(self) -> list[dict]:
        """Scrape all Premier League games and return clean sheet odds dicts."""
        stubs = await self._get_game_list()
        if not stubs:
            logger.info("No Premier League games found on MarathonBet")
            return []

        logger.info("Processing %d games", len(stubs))
        sem = asyncio.Semaphore(2)

        async def _run(stub: dict) -> dict:
            async with sem:
                await asyncio.sleep(1.5)
                return asdict(await self._scrape_game(stub))

        results = await asyncio.gather(*(_run(s) for s in stubs))
        return list(results)

    async def _get_game_list(self) -> list[dict]:
        """Navigate to the league page and collect game stubs.

        Game cards use .coupon-row elements with data attributes:
          data-event-name  = "Home vs Away"
          data-event-path  = "Football/Israel/Premier+League/Home+vs+Away"
          data-event-treeid = 27853258  (used in the game URL)
        """
        page = await self._new_page()
        stubs: list[dict] = []
        try:
            await page.goto(LEAGUE_URL, wait_until="networkidle", timeout=30_000)

            games = await page.evaluate(
                """
                () => {
                    const rows = document.querySelectorAll('[data-event-name][data-event-path][data-event-treeid]');
                    return [...rows].map(el => ({
                        name:   el.getAttribute('data-event-name'),
                        path:   el.getAttribute('data-event-path'),
                        treeId: el.getAttribute('data-event-treeid'),
                    }));
                }
                """
            )
            logger.info("Found %d game rows on league page", len(games))

            for g in games:
                name = g.get("name") or ""
                if " vs " not in name:
                    continue
                home_t, away_t = (t.strip() for t in name.split(" vs ", 1))
                tree_id = g.get("treeId") or ""
                path = g.get("path") or ""
                url = f"{BASE_URL}/en/betting/{path}+-+{tree_id}"
                stubs.append(
                    {"homeTeam": home_t, "awayTeam": away_t, "gameId": tree_id, "url": url}
                )

            logger.info("Collected %d games", len(stubs))
        except Exception:
            logger.exception("Failed to collect game list")
        finally:
            await page.close()
        return stubs

    async def _scrape_game(self, stub: dict) -> MarathonGame:
        home, away, gid = stub["homeTeam"], stub["awayTeam"], stub["gameId"]
        _no = MarathonGame(
            homeTeam=home, awayTeam=away, gameId=gid,
            homeCleanSheetPct=None, awayCleanSheetPct=None,
            noData=True,
        )
        page = await self._new_page()
        try:
            await page.goto(stub["url"], wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(3000)

            odds = await self._extract_to_score(page)
            if not odds:
                logger.info("No 'to Score' market: %s vs %s", home, away)
                return _no

            # odds is a list of {team, noOdds} dicts — match to home/away by name
            home_no = _match_odds(odds, home)
            away_no = _match_odds(odds, away)

            if home_no is None or away_no is None:
                logger.info(
                    "Could not match teams in 'to Score' market: %s vs %s | found: %s",
                    home, away, [o["team"] for o in odds],
                )
                return _no

            # homeCleanSheetPct = P(away scores 0) = 1 / away_no_odds
            # awayCleanSheetPct = P(home scores 0) = 1 / home_no_odds
            home_cs = round(100 / away_no, 1)
            away_cs = round(100 / home_no, 1)

            logger.info(
                "%s vs %s → homeCS=%.1f%% awayCS=%.1f%%",
                home, away, home_cs, away_cs,
            )
            return MarathonGame(
                homeTeam=home, awayTeam=away, gameId=gid,
                homeCleanSheetPct=home_cs,
                awayCleanSheetPct=away_cs,
                noData=False,
            )

        except Exception:
            logger.exception("Error scraping game %s vs %s", home, away)
            return _no
        finally:
            await page.close()

    async def _extract_to_score(self, page) -> list[dict] | None:
        """
        Extract [{team, yesOdds, noOdds}, ...] from the 'Team to Score' market.

        MarathonBet displays this as a Yes/No table:
          Yes    No
          Team A to Score  1.23  3.64
          Team B to Score  1.54  2.28

        Returns None if the market is not present.
        """
        return await page.evaluate(
            """
            () => {
                const SCORE_RE = /^(.+?)\\s+to\\s+Score$/i;
                const results = [];

                // Each "X to Score" market is a <tr> with:
                //   - a <td> whose text matches the regex
                //   - two <td class="price ..."> cells: [0]=Yes odds, [1]=No odds
                document.querySelectorAll('tr').forEach(tr => {
                    const labelTd = [...tr.querySelectorAll('td')].find(
                        td => SCORE_RE.test(td.textContent.trim())
                    );
                    if (!labelTd) return;

                    const teamName = labelTd.textContent.trim()
                        .replace(/\\s+to\\s+Score$/i, '').trim();
                    const priceTds = [...tr.querySelectorAll('td.price')];
                    if (priceTds.length < 2) return;

                    results.push({
                        team:     teamName,
                        yesOdds:  parseFloat(priceTds[0].textContent.trim()),
                        noOdds:   parseFloat(priceTds[1].textContent.trim()),
                    });
                });

                return results.length ? results : null;
            }
            """
        )


def _match_odds(odds: list[dict], team_name: str) -> float | None:
    """Find the noOdds for a team by fuzzy name match."""
    team_lower = team_name.lower()

    # Exact match first
    for o in odds:
        if o["team"].lower() == team_lower:
            return o["noOdds"]

    # Partial match: one name contains the other
    for o in odds:
        other = o["team"].lower()
        if team_lower in other or other in team_lower:
            return o["noOdds"]

    # Word-overlap: majority of words match
    team_words = set(team_lower.split())
    best_score, best_no = 0, None
    for o in odds:
        other_words = set(o["team"].lower().split())
        overlap = len(team_words & other_words)
        if overlap > best_score:
            best_score = overlap
            best_no = o["noOdds"]

    return best_no if best_score > 0 else None

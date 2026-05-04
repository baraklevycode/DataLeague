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
from fetcher.config import Settings, build_scores365_id_map, build_sport5_id_map
from fetcher.schemas import Scores365GameRef, Sport5PlayerDetail
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


def _remap_365_rounds_to_overall(
    games: list[Scores365GameRef],
    sport5_details: dict[int, Sport5PlayerDetail],
) -> list[Scores365GameRef]:
    """Remap each 365Scores game's roundNum to our overall seq_round.

    Why: 365Scores' roundNum is unreliable for the playoff stage. Their
    /games/results/ endpoint may emit roundNum 27, 28, 30 (skipping 29) for
    one bracket, while /games/fixtures/ restarts the playoff stage at 1, 2,
    3, 4… Trusting it caused per-round xA to land in the wrong round or be
    dropped entirely. Sport5's roundIds are the source of truth.

    Strategy: build (team_a_internal, team_b_internal) → sorted seq_round list
    from Sport5 fixtures. For each pair, sort 365's matching games by start_time
    and zip them onto the Sport5 round list — chronological alignment is
    unambiguous even when (a) regular-season and playoff-stage roundNums
    collide, or (b) the same pair plays multiple times across the season.
    Games dated before the current-season window are dropped so prior-season
    game IDs leaking through results-paging don't contaminate current rounds.
    """
    # Build sport5 roundId -> seq_round (1..N) — same convention as
    # DataProcessor._build_round_map. Include both sources of round IDs so a
    # game whose roundId only appears in gameStats still gets a seq.
    all_round_ids: set[int] = set()
    for detail in sport5_details.values():
        for rs in detail.roundsStats:
            all_round_ids.add(rs.roundId)
        for gs in detail.gameStats:
            all_round_ids.add(gs.roundId)
    round_map = {rid: i + 1 for i, rid in enumerate(sorted(all_round_ids))}
    if not round_map:
        return games

    s5_to_internal = {tm.sport5_id: tm.internal_id for tm in build_sport5_id_map().values()}
    s365_to_internal = {tm.scores365_id: tm.internal_id for tm in build_scores365_id_map().values()}

    # Sport5 fixtures: pair → sorted list of seq_rounds the pair played in.
    from collections import defaultdict
    pair_to_rounds: dict[frozenset[int], list[int]] = defaultdict(list)
    for detail in sport5_details.values():
        for gs in detail.gameStats:
            seq = round_map.get(gs.roundId, 0)
            if not seq:
                continue
            home_s5 = gs.playerTeamId if gs.isHome else gs.opponentId
            away_s5 = gs.opponentId if gs.isHome else gs.playerTeamId
            home_internal = s5_to_internal.get(home_s5)
            away_internal = s5_to_internal.get(away_s5)
            if not home_internal or not away_internal:
                continue
            key = frozenset({home_internal, away_internal})
            if seq not in pair_to_rounds[key]:
                pair_to_rounds[key].append(seq)
    for key in pair_to_rounds:
        pair_to_rounds[key].sort()

    # Drop games whose date predates the current-season window. We bound the
    # window using the latest start_time we see and keep ~12 months back.
    def _year_month(s: str) -> tuple[int, int] | None:
        if not s or len(s) < 7:
            return None
        try:
            return int(s[:4]), int(s[5:7])
        except ValueError:
            return None
    latest = max((_year_month(g.start_time) for g in games if _year_month(g.start_time)), default=None)
    if latest is not None:
        cutoff_y, cutoff_m = latest
        cutoff_m -= 11
        while cutoff_m <= 0:
            cutoff_m += 12
            cutoff_y -= 1
    else:
        cutoff_y, cutoff_m = (0, 0)

    fresh_games: list[Scores365GameRef] = []
    dropped_old = 0
    for g in games:
        ym = _year_month(g.start_time)
        if ym is not None and (ym[0], ym[1]) < (cutoff_y, cutoff_m):
            dropped_old += 1
            continue
        fresh_games.append(g)

    # Group 365 games by team-pair so we can assign each pair's games to the
    # right Sport5 seq_round.
    games_by_pair: dict[frozenset[int], list[Scores365GameRef]] = defaultdict(list)
    unpaired: list[Scores365GameRef] = []
    for g in fresh_games:
        h_int = s365_to_internal.get(g.home_team_id)
        a_int = s365_to_internal.get(g.away_team_id)
        if not h_int or not a_int:
            unpaired.append(g)
            continue
        games_by_pair[frozenset({h_int, a_int})].append(g)

    # Pass 1 — confident assignments: pairs where 365 has exactly as many
    # games as Sport5 has fixtures. Zip chronologically. These give us a
    # data-derived seq_round → expected_date map that we use in Pass 2.
    out: list[Scores365GameRef] = list(unpaired)
    remapped_count = 0
    dropped_unmatched = 0
    seq_dates: dict[int, list[str]] = defaultdict(list)
    deferred: list[tuple[frozenset[int], list[Scores365GameRef], list[int]]] = []

    for pair, gs in games_by_pair.items():
        candidates = pair_to_rounds.get(pair, [])
        if not candidates:
            # Pair never played in current Sport5 data — drop.
            dropped_unmatched += len(gs)
            continue
        gs_sorted = sorted(gs, key=lambda x: x.start_time or "")
        if len(gs_sorted) == len(candidates):
            for game, seq in zip(gs_sorted, candidates):
                if seq != game.round_num:
                    remapped_count += 1
                out.append(game.model_copy(update={"round_num": seq}))
                if game.start_time:
                    seq_dates[seq].append(game.start_time)
        else:
            deferred.append((pair, gs_sorted, candidates))

    # Build seq_round → median date (use the middle observed start_time).
    seq_median: dict[int, str] = {}
    for seq, dates in seq_dates.items():
        dates.sort()
        seq_median[seq] = dates[len(dates) // 2]

    # Pass 2 — ambiguous pairs (M ≠ N). For each 365 game, only assign it to
    # a candidate seq if the date is within ~10 days of that seq's median
    # date. Each candidate seq can be assigned at most once per pair (so we
    # don't double-fill). Drops anything that can't find a close enough match
    # — better to leave a round empty than to backfill with stale stats.
    DAY = 86400
    TOLERANCE_DAYS = 10

    def _epoch(s: str) -> float | None:
        if not s:
            return None
        try:
            from datetime import datetime
            # 2026-05-02T20:30:00+03:00
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            return None

    for pair, gs_sorted, candidates in deferred:
        used: set[int] = set()
        for game in gs_sorted:
            ge = _epoch(game.start_time)
            if ge is None:
                dropped_unmatched += 1
                continue
            best_seq = None
            best_diff = None
            for seq in candidates:
                if seq in used:
                    continue
                med = seq_median.get(seq)
                if not med:
                    continue
                me = _epoch(med)
                if me is None:
                    continue
                diff = abs(ge - me)
                if best_diff is None or diff < best_diff:
                    best_diff, best_seq = diff, seq
            if best_seq is not None and best_diff is not None and best_diff <= TOLERANCE_DAYS * DAY:
                used.add(best_seq)
                if best_seq != game.round_num:
                    remapped_count += 1
                out.append(game.model_copy(update={"round_num": best_seq}))
            else:
                dropped_unmatched += 1

    if remapped_count or dropped_old or dropped_unmatched:
        logger.info(
            "365Scores round remap: %d games re-keyed, %d prior-season "
            "dropped, %d unmatched dropped",
            remapped_count, dropped_old, dropped_unmatched,
        )
    return out


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
        s365_stats, completed_games = await asyncio.gather(
            s365.get_all_athletes_stats(athlete_ids),
            s365.get_completed_games(),
        )
        # 365Scores' roundNum is unreliable for playoffs (skips numbers, restarts).
        # Remap each finished game to our overall seq_round by matching home/away
        # team IDs against Sport5 fixtures, and drop prior-season games whose
        # game IDs leak in via results-paging.
        completed_games = _remap_365_rounds_to_overall(completed_games, sport5_details)
        s365_round_by_athlete = await s365.get_all_game_player_stats(completed_games)
        logger.info(
            "365Scores: %d athletes resolved, %d with season stats, %d games processed (%.1fs)",
            len(s365_id_map), len(s365_stats), len(completed_games), time.time() - t2,
        )

    # Build sport5_id -> 365 stats
    s365_by_sport5: dict[int, dict] = {}
    for sport5_id, athlete_id in s365_id_map.items():
        if athlete_id in s365_stats:
            s365_by_sport5[sport5_id] = s365_stats[athlete_id]

    # Convert per-round 365 stats from athlete-id-keyed to sport5-id-keyed
    athlete_to_sport5 = {aid: sid for sid, aid in s365_id_map.items()}
    s365_round_by_sport5: dict[int, dict[int, dict]] = {}
    for rnd, by_athlete in s365_round_by_athlete.items():
        bucket: dict[int, dict] = {}
        for aid, stats in by_athlete.items():
            sid = athlete_to_sport5.get(aid)
            if sid is not None:
                bucket[sid] = stats
        if bucket:
            s365_round_by_sport5[rnd] = bucket

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
        s365_round_by_sport5=s365_round_by_sport5,
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

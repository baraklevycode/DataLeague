"""Transform raw API data into output JSON structures."""

from __future__ import annotations

import logging
from typing import Any

from fetcher.clients.sport5 import Sport5Client
from fetcher.config import POSITIONS, TEAM_MAPPINGS, build_scores365_id_map
from fetcher.schemas import (
    OutputFootballCoIlStats,
    OutputLeaderEntry,
    OutputMeta,
    OutputPlayer,
    OutputScores365Stats,
    OutputSport5Stats,
    OutputTeam,
    OutputTeamStandings,
    Scores365StandingRow,
    Sport5PlayerDetail,
)
from fetcher.services.matcher import MatchedPlayer

logger = logging.getLogger(__name__)


class DataProcessor:
    def __init__(
        self,
        matched_players: list[MatchedPlayer],
        sport5_teams: list[dict],
        sport5_details: dict[int, Sport5PlayerDetail],
        fc_season_stats: list[dict],
        fc_round_stats: dict[int, list[dict]],
        standings: list[Scores365StandingRow],
        fc_team_id_map: dict[int, int],
        s365_game_data: dict[int, list[tuple[int, list[Scores365PlayerGameStats]]]],
        unmatched_names: list[str],
    ) -> None:
        self.matched_players = matched_players
        self.sport5_teams = sport5_teams
        self.sport5_details = sport5_details
        self.fc_season_stats = fc_season_stats
        self.fc_round_stats = fc_round_stats
        self.standings = standings
        self.fc_team_id_map = fc_team_id_map
        self.s365_game_data = s365_game_data
        self.unmatched_names = unmatched_names

        # FC stats index
        self._fc_season_by_pid: dict[int, dict] = {}
        self._fc_round_by_pid: dict[int, dict[int, dict]] = {}
        self._sport5_to_fc: dict[int, int] = {}

        # 365 aggregated per-player season stats (matched by minutes+goals fingerprint)
        # sport5_id -> {xG, xA, ...}
        self._s365_player_season: dict[int, dict[str, float]] = {}

        self._index_fc_season()
        self._index_fc_rounds()
        self._match_fc_stats()
        self._match_365_stats()

        # Log unmapped FC teamIds (transferred players)
        all_fc_tids = {row.get("teamId") for row in self.fc_season_stats if row.get("teamId", -1) != -1}
        unmapped = all_fc_tids - set(self.fc_team_id_map.keys())
        if unmapped:
            logger.debug("FC teamIds not in mapping (transferred players): %s", unmapped)

    def _index_fc_season(self) -> None:
        for row in self.fc_season_stats:
            pid = row.get("playerId", -1)
            if pid != -1:
                self._fc_season_by_pid[pid] = row

    def _index_fc_rounds(self) -> None:
        for rnd, stats_list in self.fc_round_stats.items():
            for row in stats_list:
                pid = row.get("playerId", -1)
                if pid != -1:
                    self._fc_round_by_pid.setdefault(pid, {})[rnd] = row

    def _match_fc_stats(self) -> None:
        """Match FC stats rows to Sport5 players by team + goals + minutes fingerprint."""
        # Group FC stats by internal team
        fc_by_internal_team: dict[int, list[dict]] = {}
        for row in self.fc_season_stats:
            fc_tid = row.get("teamId", -1)
            internal_id = self.fc_team_id_map.get(fc_tid)
            if internal_id is not None:
                fc_by_internal_team.setdefault(internal_id, []).append(row)

        matched_fc_pids: set[int] = set()

        for mp in self.matched_players:
            if not mp.team or not mp.sport5_id:
                continue
            detail = self.sport5_details.get(mp.sport5_id)
            if not detail or not detail.seasonStats:
                continue

            sd_str = detail.seasonStats.get("statsData", "")
            sd = Sport5Client.parse_stats_data(sd_str)
            s5_goals = sd.Goals.Count
            s5_minutes = sd.MinutesPlayed.Count
            s5_appearances = sd.OpenLineup.Count + sd.SubstituteIn.Count

            if s5_minutes == 0 and s5_goals == 0:
                continue

            candidates = fc_by_internal_team.get(mp.team.internal_id, [])
            best_match = None
            best_score = float("inf")

            for fc_row in candidates:
                fc_pid = fc_row.get("playerId", -1)
                if fc_pid in matched_fc_pids:
                    continue

                fc_goals = int(fc_row.get("Goal", 0))
                fc_minutes = int(fc_row.get("totalMinutesPlayed", 0))
                fc_apps = int(fc_row.get("appearances", 0))

                # Score based on how close goals+minutes+appearances match
                goal_diff = abs(s5_goals - fc_goals)
                min_diff = abs(s5_minutes - fc_minutes) / max(s5_minutes, 1) if s5_minutes > 0 else abs(fc_minutes) / 100
                app_diff = abs(s5_appearances - fc_apps)

                # Goals must match exactly or very close
                if goal_diff > 2:
                    continue

                score = goal_diff * 10 + min_diff * 5 + app_diff

                if score < best_score:
                    best_score = score
                    best_match = fc_row

            if best_match and best_score < 15:
                fc_pid = best_match["playerId"]
                self._sport5_to_fc[mp.sport5_id] = fc_pid
                matched_fc_pids.add(fc_pid)
                mp.fc_stats_player_id = fc_pid

        logger.info("Matched %d Sport5 players to FC stats", len(self._sport5_to_fc))

    def _match_365_stats(self) -> None:
        """Match anonymous 365Scores per-game stats to Sport5 players.

        Strategy: for each round+team, match 365 anonymous entries to Sport5 players
        by comparing minutes+goals within that team's lineup for that round.
        Then aggregate xA across all rounds per player.
        """
        from fetcher.config import build_scores365_id_map
        s365_to_internal = {tm.scores365_id: tm for tm in TEAM_MAPPINGS}

        round_map = self._build_round_map()

        # Build Sport5 per-round stats indexed by (seq_round, internal_team_id) -> list of (sport5_id, goals, minutes)
        s5_round_players: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
        for mp in self.matched_players:
            if not mp.sport5_id or not mp.team:
                continue
            detail = self.sport5_details.get(mp.sport5_id)
            if not detail:
                continue
            for rs in detail.roundsStats:
                seq = round_map.get(rs.roundId)
                if seq is None:
                    continue
                sd = Sport5Client.parse_stats_data(rs.statsData)
                key = (seq, mp.team.internal_id)
                s5_round_players.setdefault(key, []).append(
                    (mp.sport5_id, sd.Goals.Count, sd.MinutesPlayed.Count)
                )

        # Aggregate 365 xA per sport5_id
        player_xg_sum: dict[int, float] = {}
        player_xa_sum: dict[int, float] = {}
        player_game_count: dict[int, int] = {}

        for rnd, game_list in self.s365_game_data.items():
            for _gid, players_stats in game_list:
                # Group 365 entries by team
                by_team: dict[int, list[Scores365PlayerGameStats]] = {}
                for ps in players_stats:
                    by_team.setdefault(ps.team_id, []).append(ps)

                for s365_tid, s365_entries in by_team.items():
                    tm = s365_to_internal.get(s365_tid)
                    if not tm:
                        continue

                    s5_entries = s5_round_players.get((rnd, tm.internal_id), [])
                    if not s5_entries:
                        continue

                    # Match by minutes + goals fingerprint
                    used_s5: set[int] = set()
                    for s365_p in s365_entries:
                        s365_mins = int(s365_p.stats.get("minutes", 0))
                        s365_goals = int(s365_p.stats.get("goals", 0))
                        if s365_mins == 0:
                            continue

                        best_s5_id = None
                        best_diff = float("inf")
                        for s5_id, s5_goals, s5_mins in s5_entries:
                            if s5_id in used_s5 or s5_mins == 0:
                                continue
                            min_diff = abs(s5_mins - s365_mins)
                            goal_diff = abs(s5_goals - s365_goals)
                            # Minutes must be within 5, goals must match exactly
                            if goal_diff == 0 and min_diff <= 5:
                                diff = min_diff
                                if diff < best_diff:
                                    best_diff = diff
                                    best_s5_id = s5_id

                        if best_s5_id is not None:
                            used_s5.add(best_s5_id)
                            xg = s365_p.stats.get("xG", 0)
                            xa = s365_p.stats.get("xA", 0)
                            player_xg_sum[best_s5_id] = player_xg_sum.get(best_s5_id, 0) + xg
                            player_xa_sum[best_s5_id] = player_xa_sum.get(best_s5_id, 0) + xa
                            player_game_count[best_s5_id] = player_game_count.get(best_s5_id, 0) + 1

        # Store aggregated season stats
        for s5_id in player_xg_sum:
            self._s365_player_season[s5_id] = {
                "xG": round(player_xg_sum.get(s5_id, 0), 2),
                "xA": round(player_xa_sum.get(s5_id, 0), 2),
                "games": player_game_count.get(s5_id, 0),
            }

        logger.info("Matched 365Scores xA data for %d players", len(self._s365_player_season))

    def _build_round_map(self) -> dict[int, int]:
        all_round_ids: set[int] = set()
        for detail in self.sport5_details.values():
            for rs in detail.roundsStats:
                all_round_ids.add(rs.roundId)
        sorted_ids = sorted(all_round_ids)
        return {rid: i + 1 for i, rid in enumerate(sorted_ids)}

    def build_players(self) -> list[dict]:
        players: list[dict] = []

        for mp in self.matched_players:
            sport5_stats = None
            total_pts = 0
            detail = self.sport5_details.get(mp.sport5_id) if mp.sport5_id else None
            if detail and detail.seasonStats:
                sd_str = detail.seasonStats.get("statsData", "")
                sd = Sport5Client.parse_stats_data(sd_str)
                total_pts = detail.seasonStats.get("points", 0) or detail.seasonStats.get("totalPoints", 0)
                sport5_stats = OutputSport5Stats(
                    totalPoints=total_pts,
                    minutesPlayed=sd.MinutesPlayed.Count,
                    goals=sd.Goals.Count,
                    goalsPoints=sd.Goals.Points,
                    assists=sd.Assists.Count,
                    assistsPoints=sd.Assists.Points,
                    yellowCards=sd.YellowCards.Count,
                    yellowCardsPoints=sd.YellowCards.Points,
                    redCards=sd.RedCards.Count,
                    openLineup=sd.OpenLineup.Count,
                    substituteIn=sd.SubstituteIn.Count,
                    substituteOut=sd.SubstituteOut.Count,
                    cleanSheets=sd.CleanGames.Count,
                    ownGoals=sd.OwnGoals.Count,
                    penaltiesStopped=sd.PenaltiesStopped.Count,
                    penaltiesMissed=sd.PenaltiesMissed.Count,
                    causedPenalty=sd.CausedPenalty.Count,
                    failedForPenalty=sd.FailedForPenalty.Count,
                ).model_dump()

            # Football.co.il stats (matched by fingerprint)
            fc_stats = None
            fc_pid = self._sport5_to_fc.get(mp.sport5_id) if mp.sport5_id else None
            if fc_pid and fc_pid in self._fc_season_by_pid:
                s = self._fc_season_by_pid[fc_pid]
                fc_stats = OutputFootballCoIlStats(
                    expectedGoals=_fval(s, "expectedGoals"),
                    goals=int(_fval(s, "Goal")),
                    assists=int(_fval(s, "Assist")),
                    shotsOnTarget=int(_fval(s, "OnTarget")),
                    shotAttempts=int(_fval(s, "AttemptonGoal", "totalScoringAtt")),
                    totalMinutesPlayed=int(_fval(s, "totalMinutesPlayed")),
                    yellowCards=int(_fval(s, "YellowCard")),
                    redCards=int(_fval(s, "RedCard")),
                    appearances=int(_fval(s, "appearances")),
                    passes=int(_fval(s, "passes", "accuratePasses")),
                ).model_dump()

            # 365Scores xA from matched game data
            s365_stats = None
            xa_val = 0.0
            s365_matched = self._s365_player_season.get(mp.sport5_id) if mp.sport5_id else None
            if s365_matched:
                xa_val = s365_matched.get("xA", 0.0)

            # Sport5 player basic info
            sp_basic = None
            if mp.sport5_id:
                for t in self.sport5_teams:
                    for p in t.get("players", []):
                        if p.get("id") == mp.sport5_id:
                            sp_basic = p
                            break
                    if sp_basic:
                        break

            raw_img = sp_basic.get("imagePath", "") if sp_basic else ""
            image_url = raw_img if raw_img and "/Files/" in raw_img else ""
            player_price = int(sp_basic.get("price", 0)) if sp_basic else 0

            player = OutputPlayer(
                id=mp.internal_id,
                name=mp.name_he,
                englishName=mp.name_en,
                team=mp.team.name_he if mp.team else "",
                teamId=mp.team.internal_id if mp.team else 0,
                position=sp_basic.get("position", 0) if sp_basic else 0,
                price=player_price,
                shirtNumber=sp_basic.get("shirtNumber", 0) if sp_basic else 0,
                imageUrl=image_url or "",
                injuredStatus=sp_basic.get("injuredStatus", 0) if sp_basic else 0,
                expelledStatus=sp_basic.get("expelledStatus", 0) if sp_basic else 0,
                missingStatus=sp_basic.get("missingStatus", 0) if sp_basic else 0,
                timesSelected=detail.timesSelected if detail else 0,
                avgPoints=detail.avgPoints if detail else 0.0,
                ppm=round(total_pts / (player_price / 1_000_000), 2) if player_price > 0 and total_pts else 0.0,
                xA=round(xa_val, 2),
                xGI=round((fc_stats.get("expectedGoals", 0) if isinstance(fc_stats, dict) else 0) + xa_val, 2),
                sport5=sport5_stats,
                footballCoIl=fc_stats,
                scores365=s365_stats,
            )
            players.append(player.model_dump())

        return players

    def build_teams(self) -> list[dict]:
        standings_by_s365: dict[int, Scores365StandingRow] = {
            s.competitor_id: s for s in self.standings
        }

        teams: list[dict] = []
        for tm in TEAM_MAPPINGS:
            standing = standings_by_s365.get(tm.scores365_id)
            standings_data = None
            if standing:
                standings_data = OutputTeamStandings(
                    position=standing.position,
                    played=standing.played,
                    won=standing.won,
                    drawn=standing.drawn,
                    lost=standing.lost,
                    goalsFor=standing.goals_for,
                    goalsAgainst=standing.goals_against,
                    points=standing.points,
                    recentForm=standing.recent_form,
                ).model_dump()

            player_ids = [
                mp.internal_id
                for mp in self.matched_players
                if mp.team and mp.team.internal_id == tm.internal_id
            ]

            logo_url = ""
            shirt_url = ""
            for st in self.sport5_teams:
                if st.get("id") == tm.sport5_id:
                    logo_url = st.get("logoPath", "") or ""
                    shirt_url = st.get("shirtPath", "") or ""
                    break

            team = OutputTeam(
                id=tm.internal_id,
                name=tm.name_he,
                englishName=tm.name_en,
                sport5Id=tm.sport5_id,
                scores365Id=tm.scores365_id,
                logoUrl=logo_url,
                shirtUrl=shirt_url,
                standings=standings_data,
                playerIds=player_ids,
            )
            teams.append(team.model_dump())

        return teams

    def build_rounds(self) -> dict:
        round_map = self._build_round_map()
        rounds: dict[str, Any] = {}

        for mp in self.matched_players:
            detail = self.sport5_details.get(mp.sport5_id) if mp.sport5_id else None
            if not detail:
                continue

            fc_pid = self._sport5_to_fc.get(mp.sport5_id) if mp.sport5_id else None

            for rs in detail.roundsStats:
                seq_round = round_map.get(rs.roundId)
                if seq_round is None:
                    continue
                rnd_key = str(seq_round)
                if rnd_key not in rounds:
                    stage = "RegularSeason" if seq_round <= 26 else "Playoffs"
                    rounds[rnd_key] = {
                        "stage": stage,
                        "sport5RoundId": rs.roundId,
                        "players": {},
                    }

                sd = Sport5Client.parse_stats_data(rs.statsData)
                sport5_round = {
                    "points": rs.totalPoints,
                    "goals": sd.Goals.Count,
                    "goalsPoints": sd.Goals.Points,
                    "assists": sd.Assists.Count,
                    "assistsPoints": sd.Assists.Points,
                    "minutesPlayed": sd.MinutesPlayed.Count,
                    "yellowCards": sd.YellowCards.Count,
                    "redCards": sd.RedCards.Count,
                    "cleanSheets": sd.CleanGames.Count,
                }

                # FC round data
                fc_round_data = None
                if fc_pid and fc_pid in self._fc_round_by_pid:
                    fc_row = self._fc_round_by_pid[fc_pid].get(seq_round)
                    if fc_row:
                        fc_round_data = {
                            "expectedGoals": _fval(fc_row, "expectedGoals"),
                            "goals": int(_fval(fc_row, "Goal")),
                            "assists": int(_fval(fc_row, "Assist")),
                            "shotsOnTarget": int(_fval(fc_row, "OnTarget")),
                            "minutesPlayed": int(_fval(fc_row, "totalMinutesPlayed")),
                        }

                pid_key = str(mp.internal_id)
                rounds[rnd_key]["players"][pid_key] = {
                    "sport5": sport5_round,
                    "footballCoIl": fc_round_data,
                    "scores365": None,
                }

        return {"rounds": rounds}

    def build_leaders(self, players: list[dict]) -> dict:
        categories = {
            "fantasyPoints": lambda p: _get_stat(p, "sport5", "totalPoints"),
            "ppm": lambda p: float(p.get("ppm", 0) or 0),
            "goals": lambda p: _get_stat(p, "sport5", "goals"),
            "expectedGoals": lambda p: _get_stat(p, "footballCoIl", "expectedGoals"),
            "assists": lambda p: _get_stat(p, "sport5", "assists"),
            "xA": lambda p: float(p.get("xA", 0) or 0),
            "xGI": lambda p: float(p.get("xGI", 0) or 0),
            "cleanSheets": lambda p: _get_stat(p, "sport5", "cleanSheets"),
            "yellowCards": lambda p: _get_stat(p, "sport5", "yellowCards"),
            "minutesPlayed": lambda p: _get_stat(p, "sport5", "minutesPlayed"),
        }

        leaders: dict[str, list[dict]] = {}
        for cat_name, extract_fn in categories.items():
            sorted_players = sorted(players, key=extract_fn, reverse=True)
            top = []
            for p in sorted_players[:20]:
                val = extract_fn(p)
                if val > 0:
                    top.append(OutputLeaderEntry(
                        playerId=p["id"],
                        name=p["name"],
                        team=p["team"],
                        value=val,
                    ).model_dump())
            leaders[cat_name] = top

        return leaders

    def build_meta(self, players: list[dict]) -> dict:
        from datetime import datetime, timezone

        matched_count = sum(
            1 for mp in self.matched_players
            if mp.fc_stats_player_id is not None
        )
        round_map = self._build_round_map()
        current_round = max(round_map.values()) if round_map else 0

        return OutputMeta(
            fetchedAt=datetime.now(timezone.utc).isoformat(),
            sport5PlayersCount=len(self.sport5_details),
            footballCoIlPlayersCount=len(self.fc_season_stats),
            scores365GamesCount=0,
            matchedPlayers=matched_count,
            unmatchedPlayers=self.unmatched_names[:50],
            currentRound=current_round,
        ).model_dump()


def _fval(data: dict, *keys: str) -> float:
    for k in keys:
        if k in data:
            try:
                return float(data[k])
            except (ValueError, TypeError):
                pass
    return 0.0


def _get_stat(player: dict, source: str, key: str) -> float:
    src = player.get(source)
    if not src:
        return 0.0
    return float(src.get(key, 0) or 0)

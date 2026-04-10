"""Transform raw API data into output JSON structures."""

from __future__ import annotations

import logging
from typing import Any

from fetcher.clients.sport5 import Sport5Client
from fetcher.config import POSITIONS, TEAM_MAPPINGS, build_scores365_id_map, build_sport5_id_map
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
        s365_by_sport5: dict[int, dict],
        unmatched_names: list[str],
    ) -> None:
        self.matched_players = matched_players
        self.sport5_teams = sport5_teams
        self.sport5_details = sport5_details
        self.fc_season_stats = fc_season_stats
        self.fc_round_stats = fc_round_stats
        self.standings = standings
        self.fc_team_id_map = fc_team_id_map
        self.s365_by_sport5 = s365_by_sport5  # sport5_id -> {xG, xA, ...}
        self.unmatched_names = unmatched_names

        # FC stats index
        self._fc_season_by_pid: dict[int, dict] = {}
        self._fc_round_by_pid: dict[int, dict[int, dict]] = {}
        self._sport5_to_fc: dict[int, int] = {}

        self._index_fc_season()
        self._index_fc_rounds()
        self._match_fc_stats()

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

        Strategy: use FC round stats as a bridge. For each round+team:
        1. Match 365 anonymous player → FC player by (goals, assists, shots, shotsOnTarget)
           with accuratePasses as tiebreaker
        2. FC playerId → Sport5 player via self._sport5_to_fc (already computed)
        3. Only accept matches that are unambiguous
        """
        s365_to_internal = {tm.scores365_id: tm for tm in TEAM_MAPPINGS}
        fc_to_s5 = {fc_pid: s5_id for s5_id, fc_pid in self._sport5_to_fc.items()}

        player_xa_sum: dict[int, float] = {}
        player_game_count: dict[int, int] = {}
        verified_matches = 0

        for rnd, game_list in self.s365_game_data.items():
            # Get FC round stats for this round
            fc_round = self._fc_round_by_pid
            fc_this_round: dict[int, dict] = {}
            for fc_pid, rounds_dict in fc_round.items():
                if rnd in rounds_dict:
                    fc_this_round[fc_pid] = rounds_dict[rnd]

            for _gid, players_stats in game_list:
                by_team: dict[int, list[Scores365PlayerGameStats]] = {}
                for ps in players_stats:
                    by_team.setdefault(ps.team_id, []).append(ps)

                for s365_tid, s365_entries in by_team.items():
                    tm = s365_to_internal.get(s365_tid)
                    if not tm:
                        continue

                    # Get FC players for this team in this round
                    fc_candidates = []
                    for fc_pid, fc_row in fc_this_round.items():
                        if fc_row.get("teamId") == tm.footballcoil_id:
                            fc_candidates.append((fc_pid, fc_row))
                    # Also check using fc_team_id_map
                    fc_team_ids = [
                        fc_tid for fc_tid, int_id in self.fc_team_id_map.items()
                        if int_id == tm.internal_id
                    ]
                    for fc_pid, fc_row in fc_this_round.items():
                        if fc_row.get("teamId") in fc_team_ids and (fc_pid, fc_row) not in fc_candidates:
                            fc_candidates.append((fc_pid, fc_row))

                    if not fc_candidates:
                        continue

                    used_fc: set[int] = set()
                    for s365_p in s365_entries:
                        s365_mins = int(s365_p.stats.get("minutes", 0))
                        if s365_mins == 0:
                            continue

                        s365_goals = int(s365_p.stats.get("goals", 0))
                        s365_assists = int(s365_p.stats.get("assists", 0))
                        s365_shots = int(s365_p.stats.get("totalShots", 0))
                        s365_on_target = int(s365_p.stats.get("shotsOnTarget", 0))
                        s365_passes = int(s365_p.stats.get("passesCompleted", 0))

                        # Find FC candidates matching (goals, assists, shots, onTarget)
                        matches: list[tuple[int, int, int]] = []  # (pass_diff, fc_pid, fc_passes)
                        for fc_pid, fc_row in fc_candidates:
                            if fc_pid in used_fc:
                                continue
                            fc_goals = int(fc_row.get("Goal", 0))
                            fc_assists = int(fc_row.get("Assist", 0))
                            fc_shots = int(fc_row.get("AttemptonGoal", fc_row.get("totalScoringAtt", 0)))
                            fc_on_target = int(fc_row.get("OnTarget", 0))
                            fc_passes = int(fc_row.get("accuratePasses", 0))

                            if (fc_goals == s365_goals and fc_assists == s365_assists
                                    and fc_shots == s365_shots and fc_on_target == s365_on_target):
                                matches.append((abs(fc_passes - s365_passes), fc_pid, fc_passes))

                        if not matches:
                            continue

                        matches.sort()
                        # Accept only if unambiguous: single match, or clear passes tiebreaker
                        accept = False
                        if len(matches) == 1:
                            accept = True
                        elif matches[0][0] < matches[1][0]:
                            accept = True

                        if accept:
                            fc_pid = matches[0][1]
                            used_fc.add(fc_pid)
                            s5_id = fc_to_s5.get(fc_pid)
                            if s5_id is not None:
                                xa = s365_p.stats.get("xA", 0)
                                player_xa_sum[s5_id] = player_xa_sum.get(s5_id, 0) + xa
                                player_game_count[s5_id] = player_game_count.get(s5_id, 0) + 1
                                verified_matches += 1

        for s5_id in player_xa_sum:
            self._s365_player_season[s5_id] = {
                "xA": round(player_xa_sum.get(s5_id, 0), 2),
                "games": player_game_count.get(s5_id, 0),
            }

        logger.info(
            "Matched 365Scores xA for %d players (%d verified round-matches)",
            len(self._s365_player_season), verified_matches,
        )

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

            # 365Scores identified stats
            s365_stats = None
            xa_val = 0.0
            s365_data = self.s365_by_sport5.get(mp.sport5_id) if mp.sport5_id else None
            if s365_data:
                xa_val = s365_data.get("xA", 0.0)
                s365_stats = OutputScores365Stats(
                    xG=s365_data.get("xG", 0.0),
                    xA=s365_data.get("xA", 0.0),
                    appearances=int(s365_data.get("appearances", 0)),
                    goals=int(s365_data.get("goals", 0)),
                    assists=int(s365_data.get("assists", 0)),
                    penaltyGoals=int(s365_data.get("penaltyGoals", 0)),
                    totalShots=int(s365_data.get("totalShots", 0)),
                    shotsOnTarget=int(s365_data.get("shotsOnTarget", 0)),
                    bigChancesCreated=int(s365_data.get("bigChancesCreated", 0)),
                    touches=int(s365_data.get("touches", 0)),
                    minutesPlayed=int(s365_data.get("minutesPlayed", 0)),
                    yellowCards=int(s365_data.get("yellowCards", 0)),
                    redCards=int(s365_data.get("redCards", 0)),
                ).model_dump()

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
                xGI=round(
                    (s365_data.get("xG", 0) if s365_data else (fc_stats.get("expectedGoals", 0) if isinstance(fc_stats, dict) else 0))
                    + xa_val, 2
                ),
                sport5=sport5_stats,
                footballCoIl=fc_stats,
                scores365=s365_stats,
            )
            pd = player.model_dump()

            # Add per-game data with opponent info
            round_map = self._build_round_map()
            if detail:
                games_list = []
                opponent_points: dict[str, int] = {}  # opponent_name -> total points
                for gs in detail.gameStats:
                    seq_round = round_map.get(gs.roundId, 0)
                    sd = Sport5Client.parse_stats_data(gs.statsData)
                    games_list.append({
                        "round": seq_round,
                        "opponent": gs.opponentName,
                        "opponentId": gs.opponentId,
                        "points": gs.points,
                        "goals": sd.Goals.Count,
                        "assists": sd.Assists.Count,
                        "isHome": gs.isHome,
                        "homeScore": gs.homeScore,
                        "awayScore": gs.awayScore,
                    })
                    if gs.opponentName:
                        opponent_points[gs.opponentName] = opponent_points.get(gs.opponentName, 0) + gs.points

                pd["games"] = sorted(games_list, key=lambda g: g["round"])
                pd["topOpponents"] = sorted(
                    [{"name": k, "points": v} for k, v in opponent_points.items()],
                    key=lambda x: x["points"], reverse=True,
                )[:3]

            # Add next game + difficulty
            if hasattr(self, '_team_next_game') and mp.team:
                ng = self._team_next_game.get(mp.team.internal_id)
                if ng:
                    opp_diff = getattr(self, '_team_difficulty', {}).get(ng.get("opponentId", 0), "medium")
                    pd["nextGame"] = ng["opponent"]
                    pd["nextGameDifficulty"] = opp_diff

            players.append(pd)

        # Mark penalty takers: per team, the player with most penalty goals
        from collections import defaultdict
        team_pen: dict[int, list[tuple[int, int]]] = defaultdict(list)  # teamId -> [(penGoals, playerIdx)]
        for i, p in enumerate(players):
            pen = 0
            if p.get("scores365") and p["scores365"].get("penaltyGoals"):
                pen = p["scores365"]["penaltyGoals"]
            elif p.get("sport5"):
                # Fallback: Sport5 tracks penalties missed but not taken
                # Use causedPenalty as a weak signal (not reliable for penalty taker)
                pass
            if pen > 0:
                team_pen[p["teamId"]].append((pen, i))

        for tid, entries in team_pen.items():
            entries.sort(reverse=True)
            if len(entries) >= 1:
                players[entries[0][1]]["isPenaltyTaker"] = True
                players[entries[0][1]]["penaltyRank"] = 1
            if len(entries) >= 2:
                players[entries[1][1]]["isPenaltyTaker2"] = True
                players[entries[1][1]]["penaltyRank"] = 2

        return players

    def build_teams(self) -> list[dict]:
        standings_by_s365: dict[int, Scores365StandingRow] = {
            s.competitor_id: s for s in self.standings
        }
        round_map = self._build_round_map()
        sport5_id_map = build_sport5_id_map()

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

            # Find next game from any player on this team
            next_game = None
            for mp in self.matched_players:
                if mp.team and mp.team.internal_id == tm.internal_id and mp.sport5_id:
                    detail = self.sport5_details.get(mp.sport5_id)
                    if detail and detail.futureGames:
                        fg = detail.futureGames[0]
                        is_home = fg["teamAId"] == tm.sport5_id
                        opp_name = fg["teamBName"] if is_home else fg["teamAName"]
                        opp_s5_id = fg["teamBId"] if is_home else fg["teamAId"]
                        # Find opponent internal ID
                        opp_tm = sport5_id_map.get(opp_s5_id)
                        next_game = {
                            "opponent": opp_name,
                            "opponentId": opp_tm.internal_id if opp_tm else 0,
                            "isHome": is_home,
                        }
                        break

            # Compute form score from recentForm
            form_score = 0
            if standings_data and standings_data.get("recentForm"):
                for f in standings_data["recentForm"]:
                    form_score += {1: 3, 2: 1, 0: 0}.get(f, 0)

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
            # Build game-by-game history for this team
            team_games: list[dict] = []
            seen_rounds: set[int] = set()
            for mp in self.matched_players:
                if not (mp.team and mp.team.internal_id == tm.internal_id and mp.sport5_id):
                    continue
                detail = self.sport5_details.get(mp.sport5_id)
                if not detail:
                    continue
                for gs in detail.gameStats:
                    seq_round = round_map.get(gs.roundId, 0)
                    if seq_round == 0 or seq_round in seen_rounds:
                        continue
                    seen_rounds.add(seq_round)
                    opp_tm = sport5_id_map.get(gs.opponentId)
                    goals_for = gs.homeScore if gs.isHome else gs.awayScore
                    goals_against = gs.awayScore if gs.isHome else gs.homeScore
                    team_games.append({
                        "round": seq_round,
                        "isHome": gs.isHome,
                        "goalsFor": goals_for,
                        "goalsAgainst": goals_against,
                        "opponentId": opp_tm.internal_id if opp_tm else 0,
                    })
            team_games.sort(key=lambda g: g["round"])

            td = team.model_dump()
            td["formScore"] = form_score
            td["nextGame"] = next_game
            td["games"] = team_games
            teams.append(td)

        # Compute form rank (1 = best form)
        teams.sort(key=lambda t: t["formScore"], reverse=True)
        for i, t in enumerate(teams):
            t["formRank"] = i + 1
            # Difficulty tier: 1-5 = hard, 6-10 = medium, 11-14 = easy
            if i < 5:
                t["difficultyTier"] = "hard"
            elif i < 10:
                t["difficultyTier"] = "medium"
            else:
                t["difficultyTier"] = "easy"

        # Build team difficulty lookup for players
        self._team_difficulty = {t["id"]: t["difficultyTier"] for t in teams}
        self._team_next_game = {}
        for t in teams:
            if t.get("nextGame"):
                self._team_next_game[t["id"]] = t["nextGame"]

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
                            "shotAttempts": int(_fval(fc_row, "AttemptonGoal", "totalScoringAtt")),
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

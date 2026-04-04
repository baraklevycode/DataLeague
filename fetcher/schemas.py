"""Pydantic schemas for API responses and output JSON structures."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sport5 API response schemas
# ---------------------------------------------------------------------------

class Sport5StatEntry(BaseModel):
    Count: int = 0
    Points: int = 0


class Sport5StatsData(BaseModel):
    MinutesPlayed: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    OpenLineup: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    SubstituteIn: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    SubstituteOut: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    Goals: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    OwnGoals: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    Assists: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    YellowCards: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    RedCards: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    PenaltiesStopped: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    PenaltiesMissed: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    CausedPenalty: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    FailedForPenalty: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    GoalsAbsorbed: Sport5StatEntry = Field(default_factory=Sport5StatEntry)
    CleanGames: Sport5StatEntry = Field(default_factory=Sport5StatEntry)


class Sport5Player(BaseModel):
    id: int
    name: str = ""
    teamId: int = 0
    price: int = 0
    position: int = 0
    shirtNumber: int = 0
    imagePath: str | None = None
    injuredStatus: int = 0
    expelledStatus: int = 0
    missingStatus: int = 0


class Sport5Team(BaseModel):
    id: int
    name: str = ""
    teamLogoPath: str = ""
    teamShirtPath: str = ""
    players: list[Sport5Player] = Field(default_factory=list)


class Sport5RoundStat(BaseModel):
    roundId: int
    totalPoints: int = 0
    statsData: str = ""  # JSON string that needs double-parsing


class Sport5GameStat(BaseModel):
    gameId: int = 0
    playerTeamId: int = 0
    points: int = 0
    statsData: str = ""
    opponentId: int = 0
    opponentName: str = ""
    roundId: int = 0
    homeScore: int = 0
    awayScore: int = 0
    isHome: bool = False


class Sport5PlayerDetail(BaseModel):
    id: int
    name: str = ""
    seasonStats: dict | None = None
    roundsStats: list[Sport5RoundStat] = Field(default_factory=list)
    gameStats: list[Sport5GameStat] = Field(default_factory=list)
    timesSelected: int = 0
    avgPoints: float = 0.0


# ---------------------------------------------------------------------------
# Football.co.il API response schemas
# ---------------------------------------------------------------------------

class FootballCoIlPlayer(BaseModel):
    id: int = Field(alias="_id", default=0)
    name: str = ""
    hebrewName: str = ""
    position: str = ""
    teamName: str = ""
    teamId: int | None = None
    instatId: int | None = None

    model_config = {"populate_by_name": True}


class FootballCoIlStatRow(BaseModel):
    playerId: int = 0
    playerName: str = ""
    teamName: str = ""
    stats: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 365Scores API response schemas
# ---------------------------------------------------------------------------

class Scores365StandingRow(BaseModel):
    competitor_id: int = 0
    competitor_name: str = ""
    position: int = 0
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    recent_form: list[int] = Field(default_factory=list)


class Scores365GameRef(BaseModel):
    game_id: int
    round_num: int = 0
    home_team_id: int = 0
    away_team_id: int = 0
    home_score: int = 0
    away_score: int = 0


class Scores365PlayerGameStats(BaseModel):
    player_id: int
    player_name: str = ""
    team_id: int = 0
    stats: dict[str, float] = Field(default_factory=dict)
    rating: float = 0.0


# ---------------------------------------------------------------------------
# Output JSON schemas
# ---------------------------------------------------------------------------

class OutputSport5Stats(BaseModel):
    totalPoints: int = 0
    minutesPlayed: int = 0
    goals: int = 0
    goalsPoints: int = 0
    assists: int = 0
    assistsPoints: int = 0
    yellowCards: int = 0
    yellowCardsPoints: int = 0
    redCards: int = 0
    openLineup: int = 0
    substituteIn: int = 0
    substituteOut: int = 0
    cleanSheets: int = 0
    ownGoals: int = 0
    penaltiesStopped: int = 0
    penaltiesMissed: int = 0
    causedPenalty: int = 0
    failedForPenalty: int = 0


class OutputFootballCoIlStats(BaseModel):
    expectedGoals: float = 0.0
    goals: int = 0
    assists: int = 0
    shotsOnTarget: int = 0
    shotAttempts: int = 0
    totalMinutesPlayed: int = 0
    yellowCards: int = 0
    redCards: int = 0
    appearances: int = 0
    passes: int = 0


class OutputScores365Stats(BaseModel):
    xG: float = 0.0
    xA: float = 0.0
    rating: float = 0.0
    appearances: int = 0
    goals: int = 0
    assists: int = 0
    penaltyGoals: int = 0
    totalShots: int = 0
    shotsOnTarget: int = 0
    bigChancesCreated: int = 0
    touches: int = 0
    minutesPlayed: int = 0
    yellowCards: int = 0
    redCards: int = 0


class OutputPlayer(BaseModel):
    id: int
    name: str = ""
    englishName: str = ""
    team: str = ""
    teamId: int = 0
    position: int = 0
    price: int = 0
    shirtNumber: int = 0
    imageUrl: str = ""
    injuredStatus: int = 0
    expelledStatus: int = 0
    missingStatus: int = 0
    timesSelected: int = 0
    avgPoints: float = 0.0
    ppm: float = 0.0  # Points Per Million (totalPoints / price_in_millions)
    xA: float = 0.0  # Expected Assists (from 365Scores game matching)
    xGI: float = 0.0  # Expected Goal Involvement = xG + xA
    sport5: OutputSport5Stats | None = None
    footballCoIl: OutputFootballCoIlStats | None = None
    scores365: OutputScores365Stats | None = None


class OutputTeamStandings(BaseModel):
    position: int = 0
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goalsFor: int = 0
    goalsAgainst: int = 0
    points: int = 0
    recentForm: list[int] = Field(default_factory=list)


class OutputTeam(BaseModel):
    id: int
    name: str = ""
    englishName: str = ""
    sport5Id: int = 0
    scores365Id: int = 0
    logoUrl: str = ""
    shirtUrl: str = ""
    standings: OutputTeamStandings | None = None
    playerIds: list[int] = Field(default_factory=list)


class OutputLeaderEntry(BaseModel):
    playerId: int
    name: str = ""
    team: str = ""
    value: float = 0.0


class OutputMeta(BaseModel):
    fetchedAt: str = ""
    sport5PlayersCount: int = 0
    footballCoIlPlayersCount: int = 0
    scores365GamesCount: int = 0
    matchedPlayers: int = 0
    unmatchedPlayers: list[str] = Field(default_factory=list)
    currentRound: int = 0

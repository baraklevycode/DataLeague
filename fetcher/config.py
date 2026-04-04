"""Configuration and cross-source team mapping."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "DDL_", "env_file": ".env", "extra": "ignore"}

    # Sport5 Dream Team
    sport5_email: str = ""
    sport5_password: str = ""
    sport5_base_url: str = "https://dreamteam.sport5.co.il/api"
    sport5_season_id: int = 6

    # Football.co.il (Bamboo Cloud)
    footballcoil_base_url: str = "https://cdnapi.bamboo-cloud.com/api/football"
    footballcoil_tournament_id: int = 902
    footballcoil_season: str = "25/26"
    footballcoil_iid: str = "573881b7181f46ae4c8b4567"

    # 365Scores
    scores365_base_url: str = "https://webws.365scores.com/web"
    scores365_competition_id: int = 42
    scores365_season_id: int = 88

    # Output
    output_dir: Path = Path("docs/data")

    # Concurrency
    sport5_max_concurrent: int = 10
    scores365_max_concurrent: int = 15


@dataclass(frozen=True)
class TeamMapping:
    """Cross-source mapping for one team."""

    internal_id: int
    name_he: str
    name_en: str
    sport5_id: int
    scores365_id: int
    footballcoil_id: int  # Bamboo Cloud team ID (confirmed from /team API)


# 14 Israeli Premier League teams — cross-mapping across all 3 sources
# Sport5 IDs from live API, FC IDs from /team endpoint, 365 IDs from standings
TEAM_MAPPINGS: list[TeamMapping] = [
    TeamMapping(1, "הפועל באר שבע", "Hapoel Beer Sheva", 130, 579, 4554),
    TeamMapping(2, "בית\"ר ירושלים", "Beitar Jerusalem", 140, 559, 4524),
    TeamMapping(3, "מכבי תל אביב", "Maccabi Tel Aviv", 133, 566, 4536),
    TeamMapping(4, "הפועל תל אביב", "Hapoel Tel Aviv", 128, 567, 4530),
    TeamMapping(5, "מכבי חיפה", "Maccabi Haifa", 138, 562, 4539),
    TeamMapping(6, "הפועל פתח תקווה", "Hapoel Petah Tikva", 134, 571, 4542),
    TeamMapping(7, "מכבי נתניה", "Maccabi Netanya", 132, 560, 4545),
    TeamMapping(8, "בני סכנין", "Bnei Sakhnin", 129, 561, 15960),
    TeamMapping(9, "הפועל קרית שמונה", "Hapoel Kiryat Shmona", 197, 563, 4563),
    TeamMapping(10, "הפועל חיפה", "Hapoel Haifa", 131, 575, 14316),
    TeamMapping(11, "מ.ס. אשדוד", "SC Ashdod", 135, 569, 4548),
    TeamMapping(12, "הפועל ירושלים", "Hapoel Jerusalem", 136, 614, 7020),
    TeamMapping(13, "עירוני טבריה", "Ironi Tiberias", 198, 606, 12039),
    TeamMapping(14, "מכבי בני ריינה", "Maccabi Bnei Reineh", 139, 45617, 30249),
]


def get_team_by_sport5_id(sport5_id: int) -> TeamMapping | None:
    return next((t for t in TEAM_MAPPINGS if t.sport5_id == sport5_id), None)


def get_team_by_scores365_id(s365_id: int) -> TeamMapping | None:
    return next((t for t in TEAM_MAPPINGS if t.scores365_id == s365_id), None)


def get_team_by_internal_id(internal_id: int) -> TeamMapping | None:
    return next((t for t in TEAM_MAPPINGS if t.internal_id == internal_id), None)


def build_sport5_id_map() -> dict[int, TeamMapping]:
    return {t.sport5_id: t for t in TEAM_MAPPINGS}


def build_scores365_id_map() -> dict[int, TeamMapping]:
    return {t.scores365_id: t for t in TEAM_MAPPINGS}


def build_footballcoil_id_map() -> dict[int, int]:
    """Map FC teamId -> internal team ID."""
    return {t.footballcoil_id: t.internal_id for t in TEAM_MAPPINGS}


# Position labels
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

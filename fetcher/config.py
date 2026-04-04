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
    footballcoil_name: str  # used as key in football.co.il data


# 14 Israeli Premier League teams — manual cross-mapping
# Sport5 IDs confirmed from live API for 25/26 season
TEAM_MAPPINGS: list[TeamMapping] = [
    TeamMapping(1, "הפועל באר שבע", "Hapoel Beer Sheva", 130, 579, "Hapoel Beer Sheva"),
    TeamMapping(2, "בית\"ר ירושלים", "Beitar Jerusalem", 140, 559, "Beitar Jerusalem"),
    TeamMapping(3, "מכבי תל אביב", "Maccabi Tel Aviv", 133, 566, "Maccabi Tel Aviv"),
    TeamMapping(4, "הפועל תל אביב", "Hapoel Tel Aviv", 128, 567, "Hapoel Tel Aviv"),
    TeamMapping(5, "מכבי חיפה", "Maccabi Haifa", 138, 562, "Maccabi Haifa"),
    TeamMapping(6, "הפועל פתח תקווה", "Hapoel Petah Tikva", 134, 571, "Hapoel Petah Tikva"),
    TeamMapping(7, "מכבי נתניה", "Maccabi Netanya", 132, 560, "Maccabi Netanya"),
    TeamMapping(8, "בני סכנין", "Bnei Sakhnin", 129, 561, "Bnei Sakhnin"),
    TeamMapping(9, "הפועל קרית שמונה", "Hapoel Kiryat Shmona", 197, 563, "Ironi Kiryat Shmona"),
    TeamMapping(10, "הפועל חיפה", "Hapoel Haifa", 131, 575, "Hapoel Haifa"),
    TeamMapping(11, "מ.ס. אשדוד", "SC Ashdod", 135, 569, "Moadon Sport Ashdod"),
    TeamMapping(12, "הפועל ירושלים", "Hapoel Jerusalem", 136, 614, "Hapoel Jerusalem"),
    TeamMapping(13, "עירוני טבריה", "Ironi Tiberias", 198, 606, "Ironi Tiberias"),
    TeamMapping(14, "מכבי בני ריינה", "Maccabi Bnei Reineh", 139, 45617, "Maccabi Bnei Reineh"),
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


def build_footballcoil_name_map() -> dict[str, TeamMapping]:
    return {t.footballcoil_name.lower(): t for t in TEAM_MAPPINGS}


# Position labels
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

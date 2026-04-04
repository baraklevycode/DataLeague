"""3-way player name matching across Sport5, Football.co.il, and 365Scores."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

from fetcher.config import (
    TeamMapping,
    build_sport5_id_map,
)

logger = logging.getLogger(__name__)


@dataclass
class MatchedPlayer:
    """A player matched across sources."""

    internal_id: int
    name_he: str = ""
    name_en: str = ""
    team: TeamMapping | None = None

    sport5_id: int | None = None
    fc_stats_player_id: int | None = None
    scores365_id: int | None = None

    sport5_team_id: int | None = None


def normalize_name(name: str) -> str:
    """Normalize a player name for comparison."""
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\u0590-\u05FFa-zA-Z0-9\s]", "", stripped)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.lower()


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


@dataclass
class PlayerMatcher:
    """Matches Sport5 players to FC player names (for English names)."""

    sport5_players: list[dict] = field(default_factory=list)
    footballcoil_players: list[dict] = field(default_factory=list)
    scores365_players: list[dict] = field(default_factory=list)

    matched: list[MatchedPlayer] = field(default_factory=list)
    unmatched_sport5: list[str] = field(default_factory=list)
    unmatched_scores365: list[str] = field(default_factory=list)

    def match_all(self) -> list[MatchedPlayer]:
        sport5_id_map = build_sport5_id_map()

        # Index FC player names by normalized Hebrew name
        fc_by_hebrew: dict[str, dict] = {}
        for p in self.footballcoil_players:
            he_norm = normalize_name(p.get("hebrewName", ""))
            if he_norm:
                fc_by_hebrew[he_norm] = p

        # Index 365Scores players
        s365_by_name: dict[str, dict] = {}
        s365_by_team_name: dict[tuple[str, int], dict] = {}
        for p in self.scores365_players:
            en_norm = normalize_name(p.get("player_name", ""))
            if en_norm:
                s365_by_name[en_norm] = p
                s365_by_team_name[(en_norm, p.get("team_id", 0))] = p

        s365_matched_names: set[str] = set()
        internal_id = 0

        for sp in self.sport5_players:
            internal_id += 1
            sp_name = sp.get("name", "")
            sp_team_id = sp.get("teamId", 0)
            he_norm = normalize_name(sp_name)
            team = sport5_id_map.get(sp_team_id)

            # Match FC player names for English name
            fc_name_match = None
            if he_norm:
                fc_name_match = fc_by_hebrew.get(he_norm)
                if not fc_name_match:
                    for fc_he, fc_p in fc_by_hebrew.items():
                        if _levenshtein(he_norm, fc_he) <= 2:
                            fc_name_match = fc_p
                            break

            en_name = fc_name_match.get("name", "") if fc_name_match else ""

            # Match 365Scores by English name
            s365_match = None
            if en_name:
                en_norm = normalize_name(en_name)
                if team:
                    s365_match = s365_by_team_name.get((en_norm, team.scores365_id))
                if not s365_match:
                    s365_match = s365_by_name.get(en_norm)
                if not s365_match and en_norm:
                    for s365_en, s365_p in s365_by_name.items():
                        if _levenshtein(en_norm, s365_en) <= 2:
                            s365_match = s365_p
                            break

            s365_id = s365_match.get("player_id") if s365_match else None
            if s365_match:
                s365_matched_names.add(normalize_name(s365_match.get("player_name", "")))

            self.matched.append(MatchedPlayer(
                internal_id=internal_id,
                name_he=sp_name,
                name_en=en_name,
                team=team,
                sport5_id=sp.get("id"),
                scores365_id=s365_id,
                sport5_team_id=sp_team_id,
            ))

        logger.info(
            "Matched %d players. With English names: %d",
            len(self.matched),
            sum(1 for m in self.matched if m.name_en),
        )
        return self.matched

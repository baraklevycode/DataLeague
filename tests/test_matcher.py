"""Tests for the player matching logic."""

from fetcher.services.matcher import PlayerMatcher, normalize_name


def test_normalize_name_hebrew():
    assert normalize_name("דן ביטון") == "דן ביטון"


def test_normalize_name_english():
    assert normalize_name("Dan Biton") == "dan biton"


def test_normalize_name_strips_special_chars():
    assert normalize_name("O'Brien-Smith") == "obriensmith"


def test_normalize_name_strips_diacritics():
    assert normalize_name("José García") == "jose garcia"


def test_normalize_name_empty():
    assert normalize_name("") == ""


def test_exact_hebrew_match():
    matcher = PlayerMatcher(
        sport5_players=[
            {"id": 1, "name": "דן ביטון", "teamId": 130},
        ],
        footballcoil_players=[
            {"_id": 100, "name": "Dan Biton", "hebrewName": "דן ביטון", "teamName": "Hapoel Beer Sheva"},
        ],
        scores365_players=[
            {"player_id": 500, "player_name": "Dan Biton", "team_id": 579},
        ],
    )
    matched = matcher.match_all()
    assert len(matched) == 1
    assert matched[0].sport5_id == 1
    assert matched[0].footballcoil_id == 100
    assert matched[0].scores365_id == 500
    assert matched[0].name_en == "Dan Biton"


def test_fuzzy_hebrew_match():
    matcher = PlayerMatcher(
        sport5_players=[
            {"id": 2, "name": "דן ביטן", "teamId": 130},  # slightly different
        ],
        footballcoil_players=[
            {"_id": 101, "name": "Dan Biton", "hebrewName": "דן ביטון", "teamName": "Hapoel Beer Sheva"},
        ],
        scores365_players=[],
    )
    matched = matcher.match_all()
    assert len(matched) == 1
    assert matched[0].footballcoil_id == 101


def test_no_match():
    matcher = PlayerMatcher(
        sport5_players=[
            {"id": 3, "name": "שחקן אחר", "teamId": 130},
        ],
        footballcoil_players=[
            {"_id": 102, "name": "Totally Different", "hebrewName": "שם שונה לגמרי", "teamName": "Hapoel Beer Sheva"},
        ],
        scores365_players=[],
    )
    matched = matcher.match_all()
    assert len(matched) == 1
    assert matched[0].footballcoil_id is None


def test_multiple_players_different_teams():
    matcher = PlayerMatcher(
        sport5_players=[
            {"id": 10, "name": "יוסי כהן", "teamId": 130},
            {"id": 11, "name": "משה לוי", "teamId": 131},
        ],
        footballcoil_players=[
            {"_id": 200, "name": "Yossi Cohen", "hebrewName": "יוסי כהן", "teamName": "Hapoel Beer Sheva"},
            {"_id": 201, "name": "Moshe Levi", "hebrewName": "משה לוי", "teamName": "Beitar Jerusalem"},
        ],
        scores365_players=[],
    )
    matched = matcher.match_all()
    assert len(matched) == 2
    yossi = next(m for m in matched if m.sport5_id == 10)
    moshe = next(m for m in matched if m.sport5_id == 11)
    assert yossi.footballcoil_id == 200
    assert moshe.footballcoil_id == 201

# Israeli Premier League Fantasy Stats — Full Project Plan

## Context

Build a brand-new project that aggregates Israeli Premier League 25/26 player statistics from **three data sources** (Sport5 Dream Team, Football.co.il, and 365Scores), merges them by player name matching, and presents them in a modern static web dashboard hosted for free on **GitHub Pages**.

**Architecture:** Python script runs locally on your PC → fetches from 3 APIs → outputs static JSON data files. Pure HTML/CSS/JS frontend loads those JSON files and does all filtering/sorting in the browser. No backend server needed.

---

## Data Sources (All Confirmed Working)

### Source 1: Sport5 Dream Team API


|                 |                                                                                               |
| --------------- | --------------------------------------------------------------------------------------------- |
| **Base URL**    | `https://dreamteam.sport5.co.il/api`                                                          |
| **Season ID**   | `6`                                                                                           |
| **Auth**        | POST `/Account/Login` with `{email, password}` → returns `.AspNetCore.Cookies` session cookie |
| **Credentials** | Stored in `.env` file (never committed)                                                       |


**Endpoints:**


| Endpoint                                         | Data                                                                                                                                                             |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Players/GetTeamsAndPlayers?seasonId=6`          | 14 teams, ~850 players with: id, name, teamId, price, position (1-4), shirtNumber, imagePath, injuredStatus, expelledStatus, missingStatus, lastRoundPlayerStats |
| `Players/GetPlayerData?playerId={id}&seasonId=6` | Full player detail: profile, seasonStats, roundsStats[], gameStats, futureGames, timesSelected, avgPoints                                                        |


**Stats breakdown** (inside `statsData` — a JSON string that needs double-parsing):

- MinutesPlayed, OpenLineup, SubstituteIn, SubstituteOut, Goals, OwnGoals, Assists, YellowCards, RedCards, PenaltiesStopped, PenaltiesMissed, CausedPenalty, FailedForPenalty, GoalsAbsorbed, CleanGames
- Each has `{Count, Points}` (count = actual stat, points = fantasy points earned)

**Round IDs:** Start at `111` for 25/26 (not 1-based). Need dynamic mapping: sort all observed roundIds → assign sequential 1..N.

**Unique value:** Fantasy prices, fantasy points, fantasy points breakdown, injury/status flags, times selected by users.

---

### Source 2: Football.co.il (Bamboo Cloud API)


|                   |                                                 |
| ----------------- | ----------------------------------------------- |
| **Base URL**      | `https://cdnapi.bamboo-cloud.com/api/football/` |
| **Tournament ID** | `902`                                           |
| **Season**        | `"25/26"`                                       |
| **Auth**          | None (public API)                               |


**Common query params:** `format=json`, `iid=573881b7181f46ae4c8b4567`, `returnZeros=false`, `disableDefaultFilter=true`, `useCache=false`

**Endpoints:**


| Endpoint                                                                                     | Data                                                              |
| -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `player?expand=["instatId","teamInstatId"]&filter={"tournamentId":902,"seasonName":"25/26"}` | Player roster: id, name (English), hebrewName, position, instatId |
| `stats?filter={"tournamentId":902,"seasonName":"25/26","round":0}`                           | Season total stats                                                |
| `stats?filter={"tournamentId":902,"seasonName":"25/26","round":N,"stage":"StageName"}`       | Per-fixture stats                                                 |


**Stages & round mapping:**

- `RegularSeason` rounds 1-26 → overall 1-26
- `ChampionshipRound` rounds 1-7 → overall 27-33
- `RelegationRound` rounds 1-7 → overall 27-33

**Stats fields:** expectedGoals (xG), Assist, OnTarget, AttemptonGoal, totalMinutesPlayed, Goal, YellowCard, RedCard, appearances, Passes, CornerKicks, Offsides (30+ categories available)

**Unique value:** Expected goals (xG), detailed real match stats, both Hebrew and English player names.

---

### Source 3: 365Scores API (NEW)


|                    |                                    |
| ------------------ | ---------------------------------- |
| **Base URL**       | `https://webws.365scores.com/web/` |
| **Competition ID** | `42`                               |
| **Season**         | `88`                               |
| **Auth**           | None (public API)                  |


**Common query params:** `appTypeId=5`, `langId=15` (Hebrew), `timezoneName=Asia/Jerusalem`, `userCountryId=2`

**Endpoints:**


| Endpoint                         | Data                                                                                                              |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `stats/?competitions=42`         | Season stat leaders across 15 categories (top players per stat)                                                   |
| `standings/?competitions=42`     | Full league table: 14 teams with ids, names, W/D/L, goals, points, form                                           |
| `games/results/?competitions=42` | Completed matches with game IDs, scores, round numbers                                                            |
| `game/?gameId={id}`              | **Full match detail**: lineups, formations, per-player stats (40+ stat types), events (goals/cards/subs), ratings |


**Per-game player stats (40+ types):**

- **Attacking:** Goals, assists, shots on/off target, xG, big chances, dribbles completed, key passes
- **Defensive:** Tackles, interceptions, clearances, blocks, aerial/ground duels won
- **General:** Minutes played, touches, pass accuracy %, ball losses, fouls, cards
- **Goalkeeper:** Saves, xGA, goals conceded, sweeper actions
- **Rating:** 365Scores player rating per game (1-10 scale)

**Team IDs (365Scores → name):**


| ID    | Team                |
| ----- | ------------------- |
| 579   | Hapoel Beer Sheva   |
| 559   | Beitar Jerusalem    |
| 566   | Maccabi Tel Aviv    |
| 567   | Hapoel Tel Aviv     |
| 562   | Maccabi Haifa       |
| 571   | Hapoel Petah Tikva  |
| 560   | Maccabi Netanya     |
| 561   | Bnei Sakhnin        |
| 563   | Kiryat Shmona       |
| 575   | Hapoel Haifa        |
| 569   | SC Ashdod           |
| 614   | Hapoel Jerusalem    |
| 606   | Ironi Tiberias      |
| 45617 | Maccabi Bnei Reineh |


**Unique value:** Player ratings (1-10), detailed per-game stats (touches, duels, dribbles, pass accuracy), match events, formations/lineups.

---

## Player Matching Strategy (3-Way)

Since each source uses different player IDs, matching must be done by name:

1. **Build a master index** from Football.co.il (has both Hebrew + English names)
2. **Match Sport5 players** (Hebrew names) → Football.co.il by normalized Hebrew name
3. **Match 365Scores players** (English names) → Football.co.il by normalized English name
4. **Normalization:** strip non-alphanumeric chars, lowercase, handle Unicode (Hebrew alef-bet)
5. **Fuzzy fallback:** Levenshtein distance ≤ 2 for near-misses
6. **Log unmatched** players for manual review

**Team-level matching** (for extra confidence):

- Map team names across all 3 sources (14 teams, one-time manual mapping stored in config)
- Use team as a secondary constraint when name-matching

---

## Tech Stack


| Component                  | Technology                 | Why                                                 |
| -------------------------- | -------------------------- | --------------------------------------------------- |
| **Language**               | Python 3.11+               | User's primary language                             |
| **Package management**     | `pyproject.toml` + `pip`   | Modern Python standard                              |
| **API clients**            | `httpx` (async)            | Async HTTP for parallel fetching from 3 APIs        |
| **Data validation**        | Pydantic v2                | Strict schemas for all API responses                |
| **CLI**                    | Typer                      | Simple CLI commands (`fetch`, `export`)             |
| **Retry logic**            | Tenacity                   | Clean retry/backoff decorators                      |
| **Config**                 | Pydantic Settings + `.env` | Type-safe config with env var support               |
| **Frontend styling**       | TailwindCSS (CDN)          | Modern utility-first CSS, no build step             |
| **Frontend interactivity** | Alpine.js (CDN)            | Lightweight reactivity without React/Vue complexity |
| **Charts**                 | Chart.js (CDN)             | Beautiful charts, lightweight                       |
| **Hosting**                | GitHub Pages               | Free, static files only, custom domain support      |


**No backend needed.** The Python script outputs static JSON files. The frontend loads them directly. All filtering, sorting, and searching happens client-side in the browser (~850 players is easily handled in JS).

---

## Project Structure

```
project-root/
├── pyproject.toml                # Dependencies and project metadata
├── .env                          # SPORT5_EMAIL, SPORT5_PASSWORD (gitignored)
├── .env.example                  # Template
├── .gitignore
├── CLAUDE.md
├── README.md
│
├── fetcher/                      # Python data fetching pipeline (runs locally)
│   ├── __init__.py
│   ├── __main__.py               # python -m fetcher entry point
│   ├── cli.py                    # Typer CLI: fetch, export
│   ├── config.py                 # Pydantic Settings, all API configs, team cross-mapping
│   ├── schemas.py                # Pydantic schemas for API responses
│   │
│   ├── clients/
│   │   ├── __init__.py
│   │   ├── sport5.py             # Sport5 async client (login + fetch)
│   │   ├── footballcoil.py       # Football.co.il async client
│   │   └── scores365.py          # 365Scores async client
│   │
│   └── services/
│       ├── __init__.py
│       ├── fetcher.py            # Orchestrates all 3 API fetchers
│       ├── matcher.py            # 3-way player name matching
│       └── processor.py          # Raw API data → output JSON structure
│
├── docs/                         # GitHub Pages root (this folder gets deployed)
│   ├── index.html                # SPA shell (Alpine.js + Tailwind + Chart.js)
│   ├── css/
│   │   └── app.css               # Minimal custom styles
│   ├── js/
│   │   ├── app.js                # Main Alpine.js app, hash routing, state
│   │   ├── data.js               # Data loader (fetches JSON files)
│   │   └── components/
│   │       ├── player-table.js   # Sortable/filterable table
│   │       ├── player-card.js    # Player detail card
│   │       ├── team-card.js      # Team summary card
│   │       ├── charts.js         # Chart.js chart builders
│   │       └── filters.js        # Filter bar logic
│   │
│   └── data/                     # Static JSON data files (generated by fetcher)
│       ├── players.json          # All players with season stats from 3 sources
│       ├── teams.json            # All 14 teams with metadata + standings
│       ├── rounds.json           # Per-round player stats (all rounds, all sources)
│       ├── leaders.json          # Pre-computed leaderboards by category
│       └── meta.json             # Fetch timestamp, data freshness info
│
└── tests/
    ├── test_matcher.py
    └── test_processor.py
```

**Key:** The `docs/` folder is deployed to GitHub Pages. The `fetcher/` folder stays local on your PC.

---

## Output JSON Structure

The Python fetcher generates these JSON files in `docs/data/`:

### `players.json` — Master player file (~850 players)

```json
{
  "players": [
    {
      "id": 1,
      "name": "דן ביטון",
      "englishName": "Dan Biton",
      "team": "הפועל באר שבע",
      "teamId": 1,
      "position": 3,
      "price": 12000000,
      "shirtNumber": 10,
      "imageUrl": "https://...",
      "injuredStatus": 0,
      "expelledStatus": 0,
      "missingStatus": 0,
      "timesSelected": 45000,
      "avgPoints": 5.2,

      "sport5": {
        "totalPoints": 125,
        "minutesPlayed": 2100,
        "goals": 15, "goalsPoints": 60,
        "assists": 5, "assistsPoints": 15,
        "yellowCards": 3, "yellowCardsPoints": -3,
        "redCards": 0,
        "openLineup": 23, "substituteIn": 1, "substituteOut": 3,
        "cleanSheets": 0, "ownGoals": 0,
        "penaltiesStopped": 0, "penaltiesMissed": 0
      },
      "footballCoIl": {
        "expectedGoals": 12.5,
        "goals": 15, "assists": 5,
        "shotsOnTarget": 45, "shotAttempts": 89,
        "totalMinutesPlayed": 2100,
        "yellowCards": 3, "redCards": 0,
        "appearances": 24, "passes": 890
      },
      "scores365": {
        "avgRating": 7.3,
        "goals": 15, "assists": 5,
        "expectedGoals": 12.3, "expectedAssists": 4.1,
        "tacklesWon": 34, "interceptions": 12,
        "duelsWon": 89, "dribblesWon": 23,
        "avgPassAccuracy": 82.5, "avgTouches": 56
      }
    }
  ]
}
```

### `teams.json` — Teams with standings

```json
{
  "teams": [
    {
      "id": 1,
      "name": "הפועל באר שבע",
      "englishName": "Hapoel Beer Sheva",
      "sport5Id": 130,
      "scores365Id": 579,
      "logoUrl": "https://...",
      "shirtUrl": "https://...",
      "standings": {
        "position": 1, "played": 24,
        "won": 16, "drawn": 5, "lost": 3,
        "goalsFor": 48, "goalsAgainst": 20, "points": 53,
        "recentForm": [1, 1, 2, 1, 0]
      },
      "playerIds": [1, 5, 12, 23]
    }
  ]
}
```

### `rounds.json` — Per-round stats for all players

```json
{
  "rounds": {
    "1": {
      "stage": "RegularSeason",
      "sport5RoundId": 111,
      "players": {
        "1": {
          "sport5": { "points": 8, "goals": 1, "assists": 0, "minutesPlayed": 90, "goalsPoints": 4 },
          "footballCoIl": { "expectedGoals": 0.45, "goals": 1, "assists": 0, "shotsOnTarget": 3 },
          "scores365": { "rating": 7.8, "goals": 1, "touches": 67, "passAccuracy": 85.2, "tacklesWon": 3 }
        }
      }
    }
  }
}
```

### `leaders.json` — Pre-computed leaderboards

```json
{
  "goals": [{"playerId": 1, "name": "דן ביטון", "team": "הפועל באר שבע", "value": 15}],
  "assists": [],
  "fantasyPoints": [],
  "expectedGoals": [],
  "expectedAssists": [],
  "rating": [],
  "cleanSheets": [],
  "tacklesWon": [],
  "saves": [],
  "yellowCards": [],
  "minutesPlayed": []
}
```

### `meta.json` — Data freshness

```json
{
  "fetchedAt": "2026-04-04T15:30:00Z",
  "sport5PlayersCount": 850,
  "footballCoIlPlayersCount": 412,
  "scores365GamesCount": 168,
  "matchedPlayers": 398,
  "unmatchedPlayers": ["player1", "player2"],
  "currentRound": 24
}
```

---

## Frontend Pages

### 1. Players List (`#/players`) — Main Page

- **Sticky filter bar:** Position dropdown, Team dropdown, Price range slider, Search input (Hebrew), Round selector (Season Total / Round 1-36), Sort by dropdown
- **Results count:** "Showing 245 of 850 players"
- **Sortable table** with columns adapting to round mode:
  - **Season mode:** Name, Team, Pos, Price, Fantasy Pts, Goals, Assists, xG, xA, Rating (365), Minutes, Yellow, Red
  - **Round mode:** Name, Team, Pos, Price, Round Pts, Goals, Assists, xG, Rating, Minutes, Touches, Pass%
- Click player name → Player Detail page
- RTL layout (Hebrew primary language)

### 2. Player Detail (`#/players/{id}`)

- **Header card:** Image, name (Hebrew + English), team + logo, position badge, price, status indicators, times selected, avg points
- **3-source season stats** shown side by side in cards:
  - Sport5 card: Fantasy points with breakdown (which stats earned which points)
  - Football.co.il card: xG, shots, passes, minutes, appearances
  - 365Scores card: Avg rating, tackles, interceptions, duels, dribbles, pass accuracy
- **Round-by-round line chart** (Chart.js): Fantasy points + xG + Rating on dual axes
- **Round table:** All rounds with stats from all 3 sources per row

### 3. Teams Overview (`#/teams`)

- **14 team cards** in a responsive grid (3 cols desktop, 1 mobile)
- Each card: Logo, name, avg points, top scorer, league position, recent form dots
- Click → Team Detail

### 4. Team Detail (`#/teams/{id}`)

- Team header with logo, stats summary, league position
- Full player roster table (same columns as Players List, filtered to this team)
- Team stats aggregates

### 5. Rounds Browser (`#/rounds`)

- **Horizontal round selector:** Pills for 1-36, active round highlighted, stage labels
- **Top performers carousel:** Top 5 players by fantasy points for selected round
- **Full round table:** All players who played, sortable by all stat columns
- **Position tabs:** All / GK / Def / Mid / Fwd

### 6. Leaders (`#/leaders`)

- **Category tabs:** Goals, Assists, Fantasy Points, xG, xA, Rating, Clean Sheets, Tackles, Saves
- **Top 20 leaderboard** per category: Rank, image, name, team, stat value
- Gold/silver/bronze styling for top 3
- Horizontal bar chart for visual comparison

---

## Implementation Order

### Phase 1: Scaffolding

1. Create project directory structure
2. Write `pyproject.toml` with dependencies
3. Create `.env.example`, `.gitignore`
4. Set up virtual environment, install deps
5. Implement `fetcher/config.py` — Pydantic Settings with all 3 API configs + 14-team cross-mapping (Sport5 ID ↔ Football.co.il name ↔ 365Scores ID)
6. Implement `fetcher/schemas.py` — Pydantic models for all 3 API response shapes + output JSON shapes

### Phase 2: API Clients

1. Implement `fetcher/clients/sport5.py` — login flow, get_teams_and_players, get_player_detail (with statsData JSON double-parsing), get_all_player_details (async with semaphore, 10 concurrent max)
2. Implement `fetcher/clients/footballcoil.py` — get_players, get_season_stats, get_round_stats for all stages, get_all_round_stats (parallel by stage+round)
3. Implement `fetcher/clients/scores365.py` — get_standings, get_season_leaders, get_completed_games, get_game_detail (per-player stats + ratings), get_all_game_details (parallel, ~168 games)
4. Test each client individually against live APIs

### Phase 3: Processing Pipeline

1. Implement `fetcher/services/matcher.py` — normalize_name() for Hebrew+English, build indices from all 3 sources, 3-way matching with team constraint, fuzzy fallback, unmatched logging
2. Implement `fetcher/services/processor.py` — transform raw API data from all 3 sources into the output JSON structures (players.json, teams.json, rounds.json, leaders.json, meta.json), handle Sport5 dynamic round ID mapping, handle Football.co.il stage→round normalization
3. Implement `fetcher/services/fetcher.py` — full orchestration: login Sport5 → fetch all 3 sources in parallel → match → process → write JSON files to docs/data/
4. Implement `fetcher/cli.py` — `fetch` command (main pipeline), `export` command (CSV/Excel from the JSON)
5. Run full pipeline end-to-end, verify JSON output is correct

### Phase 4: Frontend — Structure

1. Create `docs/index.html` — SPA shell with CDN imports (Tailwind, Alpine.js, Chart.js), nav bar, router outlet
2. Implement `docs/js/data.js` — loads all JSON files, provides a data store for components
3. Implement `docs/js/app.js` — Alpine.js main app with hash-based routing, global state/stores
4. Implement `docs/js/components/filters.js` — reusable filter bar (position, team, price, search, round, sort)

### Phase 5: Frontend — Pages

1. Build Players List page (the main workhorse — filters, sortable table, season/round toggle)
2. Build Player Detail page (3-source stats cards, round-by-round chart + table)
3. Build Teams Overview page (responsive card grid with standings info)
4. Build Team Detail page (team header + filtered roster table)
5. Build Rounds Browser page (round selector pills + top performers + full round table)
6. Build Leaders page (category tabs + ranked leaderboards)

### Phase 6: Polish & Deploy

1. Responsive design pass (mobile, tablet, desktop)
2. Loading states, error handling, empty states
3. "Data last updated" indicator from meta.json
4. Deploy to GitHub Pages (enable Pages on the `docs/` folder)
5. Write tests for matcher and processor
6. Write CLAUDE.md and README.md

---

## How to Run

### Initial Setup (one time)

```bash
cd project-root

# Create virtual environment
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -e .

# Configure Sport5 credentials
copy .env.example .env
# Edit .env: set DDL_SPORT5_EMAIL and DDL_SPORT5_PASSWORD
```

### Fetch Data (run whenever you want fresh data)

```bash
python -m fetcher fetch
```

This will:

1. Login to Sport5 API
2. Fetch ~850 players from Sport5 (teams + individual player details in parallel)
3. Fetch all player stats from Football.co.il (season + all rounds/stages)
4. Fetch league standings + all completed game details from 365Scores (~168 games)
5. Match players across all 3 sources by name
6. Output JSON files to `docs/data/`

Expected time: ~5 minutes

### View Locally

```bash
# Option 1: Python built-in server
python -m http.server 8000 --directory docs

# Option 2: Just open the file
start docs/index.html
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

### Deploy to GitHub Pages

1. Push the repo to GitHub
2. In repo Settings → Pages → Source: "Deploy from branch" → Branch: `main`, folder: `/docs`
3. Site will be live at `https://username.github.io/repo-name/`

### Refresh Data on Live Site

```bash
python -m fetcher fetch          # Re-fetches all data
git add docs/data/
git commit -m "Update data"
git push                         # GitHub Pages auto-deploys
```

### Export to CSV/Excel (optional)

```bash
python -m fetcher export --format csv     # → exports/player_stats.csv
python -m fetcher export --format excel   # → exports/player_stats.xlsx
```

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "fantasy-football-il"
version = "1.0.0"
description = "Israeli Premier League Fantasy Football Statistics Aggregator"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "typer>=0.12.0",
    "tenacity>=8.0.0",
    "python-dotenv>=1.0.0",
    "pandas>=2.0.0",
    "openpyxl>=3.1.0",
]
```

No FastAPI, no SQLAlchemy, no uvicorn — much lighter dependency list.

---

## Key Design Decisions

1. **Static JSON files over a database** — ~850 players with round data is roughly 2-5MB of JSON. Browsers handle this easily. No server, no database, free hosting forever.
2. `**docs/` folder for GitHub Pages** — GitHub Pages can serve from the `/docs` folder on any branch. The fetcher writes JSON directly into `docs/data/`, so a simple `git push` deploys everything.
3. **3 separate stat blocks per player** (one per source) — Avoids deciding "which source is correct." The UI shows all 3 perspectives side-by-side. Each source has different strengths.
4. **Pre-computed leaderboards** — `leaders.json` avoids sorting 850 players in the browser for each category. Computed once during fetch.
5. **Dynamic Sport5 round mapping** — Round IDs are unpredictable (111+ for 25/26). Sort all observed IDs, assign sequential 1..N.
6. **365Scores per-game fetching** — Season stats only give top players per category. To get data for ALL players, we fetch each completed game's detail (7 games per round × ~24 rounds = ~168 game fetches). This gives full per-player per-game stats including rating, touches, pass accuracy.
7. **Team-level cross-mapping** — A manual 14-team mapping between all 3 sources' IDs/names stored in config. Used as constraint during player matching to avoid false positives.
8. **Alpine.js + Tailwind CDN** — No build step, no Node.js. Modern look and reactivity. Everything is plain HTML/JS/CSS files that GitHub Pages serves directly.
9. **Hash-based routing** (`#/players`, `#/players/5`, `#/teams`) — Works natively with static hosting. No server-side routing needed. Allows deep-linking to any player or page.

---

## Verification

After the full pipeline runs:

1. **Check `docs/data/meta.json`** — verify player counts, matched count, timestamp
2. **Check `docs/data/players.json`** — verify ~850 players, spot-check a known player (e.g., Dan Biton) has data from all 3 sources
3. **Open `docs/index.html` in browser** — verify:
  - Players table loads and displays all players
  - Filtering by position/team/price works
  - Switching to a specific round shows round-specific stats
  - Clicking a player shows the detail page with 3-source stats and chart
  - Teams page shows 14 teams with standings
  - Leaders page shows correct top 20 per category
4. **Deploy to GitHub Pages** — verify the live URL works


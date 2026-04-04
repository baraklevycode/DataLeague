# DataLeague

Israeli Premier League 25/26 Fantasy Statistics Dashboard.

Aggregates player stats from three data sources (Sport5 Dream Team, Football.co.il, 365Scores), matches them by player name, and presents them in a static web dashboard.

## Quick Start

```bash
# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install dependencies
pip install -e .

# Configure Sport5 credentials
copy .env.example .env
# Edit .env with your Sport5 email and password

# Fetch all data
python -m fetcher fetch

# View locally
python -m http.server 8000 --directory docs
# Open http://127.0.0.1:8000
```

## Data Sources

| Source | Data | Auth |
|--------|------|------|
| Sport5 Dream Team | Fantasy prices, points, status | Login required |
| Football.co.il | xG, detailed match stats, Hebrew+English names | Public |
| 365Scores | Player ratings, advanced stats (tackles, duels, etc.) | Public |

## Deploy to GitHub Pages

1. Push to GitHub
2. Settings → Pages → Source: "Deploy from branch" → Branch: main, folder: `/docs`
3. Site is live at `https://username.github.io/DataLeague/`

## Refresh Data

```bash
python -m fetcher fetch
git add docs/data/
git commit -m "Update data"
git push
```

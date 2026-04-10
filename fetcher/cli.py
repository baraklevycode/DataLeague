"""CLI entry point using Typer."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import typer

app = typer.Typer(name="fetcher", help="Israeli Premier League Fantasy Stats Fetcher")


@app.command()
def fetch() -> None:
    """Fetch data from all 3 APIs, match players, and output JSON files."""
    _setup_logging()
    from fetcher.config import Settings
    from fetcher.services.fetcher import run_pipeline

    settings = Settings()
    if not settings.sport5_email or not settings.sport5_password:
        typer.echo("Error: DDL_SPORT5_EMAIL and DDL_SPORT5_PASSWORD must be set in .env")
        raise typer.Exit(1)

    asyncio.run(run_pipeline(settings))


@app.command()
def export(
    format: str = typer.Option("csv", help="Export format: csv or excel"),
) -> None:
    """Export player data from JSON to CSV or Excel."""
    _setup_logging()
    import json

    import pandas as pd

    data_dir = Path("docs/data")
    players_file = data_dir / "players.json"

    if not players_file.exists():
        typer.echo("Error: players.json not found. Run 'fetch' first.")
        raise typer.Exit(1)

    with open(players_file, encoding="utf-8") as f:
        data = json.load(f)

    players = data["players"]

    # Flatten nested source stats
    rows = []
    for p in players:
        row = {
            "id": p["id"],
            "name": p["name"],
            "englishName": p["englishName"],
            "team": p["team"],
            "position": p["position"],
            "price": p["price"],
            "avgPoints": p["avgPoints"],
            "timesSelected": p["timesSelected"],
        }
        # Sport5 stats
        if p.get("sport5"):
            for k, v in p["sport5"].items():
                row[f"s5_{k}"] = v
        # Football.co.il stats
        if p.get("footballCoIl"):
            for k, v in p["footballCoIl"].items():
                row[f"fc_{k}"] = v
        # 365Scores stats
        if p.get("scores365"):
            for k, v in p["scores365"].items():
                row[f"s365_{k}"] = v
        rows.append(row)

    df = pd.DataFrame(rows)

    exports_dir = Path("exports")
    exports_dir.mkdir(exist_ok=True)

    if format == "csv":
        out = exports_dir / "player_stats.csv"
        df.to_csv(out, index=False, encoding="utf-8-sig")
    elif format == "excel":
        out = exports_dir / "player_stats.xlsx"
        df.to_excel(out, index=False)
    else:
        typer.echo(f"Unknown format: {format}")
        raise typer.Exit(1)

    typer.echo(f"Exported {len(rows)} players to {out}")


@app.command()
def scrape_cleansheets() -> None:
    """Scrape MarathonBet clean sheet odds and write docs/data/cleansheets.json."""
    import json
    import io
    from datetime import datetime, timezone

    # Force UTF-8 on stdout (avoids cp1252 crash on Windows)
    stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace") \
        if hasattr(sys.stdout, "buffer") else sys.stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(stream)],
    )

    from fetcher.clients.marathonbet import MarathonBetClient

    async def _run() -> None:
        async with MarathonBetClient() as client:
            games = await client.scrape_all()

        out = {
            "scrapedAt": datetime.now(timezone.utc).isoformat(),
            "games": games,
        }
        path = Path("docs/data/cleansheets.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        typer.echo(f"Wrote {len(games)} games to {path}")

    asyncio.run(_run())


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

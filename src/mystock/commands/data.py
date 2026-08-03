"""`mystock data` command group.

Structure only in this phase: no real data is fetched or downloaded.
"""

from __future__ import annotations

import typer

from mystock.common.logger import get_logger

app = typer.Typer(help="Data acquisition commands.")
logger = get_logger(__name__)


@app.command()
def fetch() -> None:
    """Fetch data from a provider (not implemented yet)."""
    logger.info("data fetch called")
    typer.echo("data fetch: not implemented yet.")


@app.command()
def update() -> None:
    """Update locally stored data (not implemented yet)."""
    logger.info("data update called")
    typer.echo("data update: not implemented yet.")

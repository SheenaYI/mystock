"""mystock CLI entry point.

Only the `data` command group is implemented in this phase. Future
command groups (research, backtest, trade) will be added as separate
Typer sub-apps once their underlying modules exist.
"""

from __future__ import annotations

import typer

from mystock.commands import data

app = typer.Typer(help="mystock: quantitative research toolkit.")
app.add_typer(data.app, name="data", help="Data acquisition commands.")


if __name__ == "__main__":
    app()

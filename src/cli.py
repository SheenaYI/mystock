"""mystock CLI entry point.

`data` and `research` command groups are implemented. Future groups
(backtest, trade) will be added as separate Typer sub-apps once their
underlying modules exist.
"""

from __future__ import annotations

import typer

from commands import data, research

app = typer.Typer(help="mystock: quantitative research toolkit.")
app.add_typer(data.app, name="data", help="Data acquisition commands.")
app.add_typer(
    research.app, name="research", help="AI-assisted quant research."
)


if __name__ == "__main__":
    app()

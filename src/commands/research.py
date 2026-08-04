"""`mystock research` command group."""

from __future__ import annotations

import typer

from common.logger import get_logger
from research.pipeline import run as run_pipeline
from research.registry import FACTOR_REGISTRY, UnsupportedFactorError

app = typer.Typer(help="AI-assisted quant research commands.")
logger = get_logger(__name__)


@app.command()
def factors() -> None:
    """List factors currently implemented and selectable via `run`."""
    typer.echo("已实现的因子：")
    for name, info in FACTOR_REGISTRY.items():
        typer.echo(f"  - {name}: {info['description']}")


@app.command()
def run(goal: str) -> None:
    """Run the full research loop for a natural-language goal."""
    logger.info("research run starting: %r", goal)
    try:
        result = run_pipeline(goal)
    except UnsupportedFactorError as exc:
        typer.echo(f"暂不支持你想要的因子：{exc.requested!r}")
        typer.echo("目前已实现的因子：")
        for name, info in FACTOR_REGISTRY.items():
            typer.echo(f"  - {name}: {info['description']}")
        typer.echo("先实现这个因子后才能用它跑 research run。")
        raise typer.Exit(code=1)

    typer.echo(f"因子: {result.experiment.factor}")
    typer.echo(f"universe: {result.universe_size} 只股票")
    typer.echo(
        f"调仓周期: {result.experiment.rebalance_days} 天, "
        f"Top {result.experiment.top_pct:.0%}, "
        f"费率: {result.experiment.fee_rate:.2%}"
    )
    typer.echo(f"本次实验累计跑了第 {result.trial_count} 次")
    typer.echo("")
    typer.echo(f"完整报告（含AI解读+图表）: {result.consolidated_report_path}")
    typer.echo(f"训练期图表: {result.train_report_path}")
    typer.echo(f"验证期图表: {result.holdout_report_path}")

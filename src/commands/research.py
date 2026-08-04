"""`mystock research` command group."""

from __future__ import annotations

import typer

from common.logger import get_logger
from research.pipeline import run as run_pipeline

app = typer.Typer(help="AI-assisted quant research commands.")
logger = get_logger(__name__)


@app.command()
def run(goal: str) -> None:
    """Run the full research loop for a natural-language goal."""
    logger.info("research run starting: %r", goal)
    result = run_pipeline(goal)

    typer.echo(f"因子: {result.experiment.factor}")
    typer.echo(f"universe: {result.universe_size} 只股票")
    typer.echo(
        f"调仓周期: {result.experiment.rebalance_days} 天, "
        f"Top {result.experiment.top_pct:.0%}, "
        f"费率: {result.experiment.fee_rate:.2%}"
    )
    typer.echo(f"本次实验累计跑了第 {result.trial_count} 次")
    typer.echo("")
    typer.echo(f"训练期报告: {result.train_report_path}")
    typer.echo(f"验证期报告: {result.holdout_report_path}")
    typer.echo("")
    typer.echo("=== AI 分析 ===")
    typer.echo(result.analysis)

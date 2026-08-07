"""`mystock research` command group."""

from __future__ import annotations

import typer

from common.logger import get_logger
from research.pipeline import run as run_pipeline
from research.comparison_report import build_s012_comparison
from common.logger import PROJECT_ROOT

app = typer.Typer(help="AI-assisted quant research commands.")
logger = get_logger(__name__)


@app.command("compare-s012")
def compare_s012() -> None:
    """Build the unified S0/S1/S2 web comparison from completed runs."""
    output = PROJECT_ROOT / "data" / "warehouse" / "reports" / "report_s012_comparison.html"
    build_s012_comparison(PROJECT_ROOT / "data" / "warehouse" / "experiments.jsonl", output)
    typer.echo(f"S0/S1/S2 对照报告: {output}")


@app.command()
def factors() -> None:
    """Show the frozen factor profile used by the formal baseline."""
    typer.echo("正式基线：technical_baseline_7（固定七因子）")


@app.command()
def run(
    profile: str = typer.Option("s0", help="m0, s0, s1, s2, s3, or all"),
    tradability_mode: str = typer.Option(
        "fail", help="fail=正式严格模式；block=缺证据订单保守阻断，仅用于诊断"
    ),
    llm_start: str | None = typer.Option(
        None, help="S3短窗口起点，例如 2024-01-01；不填则完整回放"
    ),
    llm_end: str | None = typer.Option(
        None, help="S3短窗口终点，例如 2025-12-31；不填则完整回放"
    ),
) -> None:
    """Run one frozen research profile, or all five profiles."""
    profiles = ("m0", "s0", "s1", "s2", "s3") if profile == "all" else (profile,)
    for selected_profile in profiles:
        logger.info("research profile starting: %s", selected_profile)
        result = run_pipeline(
            profile=selected_profile, tradability_mode=tradability_mode,
            llm_start=llm_start if selected_profile == "s3" else None,
            llm_end=llm_end if selected_profile == "s3" else None,
        )

        typer.echo(f"因子组: {result.experiment.factor_name}")
        typer.echo(f"universe: {result.universe_size} 只股票")
        typer.echo(
            f"调仓周期: {result.experiment.protocol.rebalance_days} 天, "
            f"TopK: {result.experiment.portfolio.top_k}, "
            f"n_drop: {result.experiment.portfolio.n_drop}"
        )
        typer.echo(f"本次实验累计跑了第 {result.trial_count} 次")
        typer.echo(f"完整报告: {result.consolidated_report_path}")
        typer.echo(f"分数与相对基准诊断: {result.diagnostics_path}")

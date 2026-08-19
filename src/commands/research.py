"""`mystock research` command group."""

from __future__ import annotations

import typer

from common.logger import get_logger
from research.pipeline import run as run_pipeline
from research.comparison_report import build_s012_comparison
from common.logger import PROJECT_ROOT
from research.jobs.manifest import JobManifest
from research.jobs.worker import run_job
from research.llm.historical_context import GoogleNewsRssSearcher, append_context

app = typer.Typer(help="AI-assisted quant research commands.")
worker_app = typer.Typer(help="可断点恢复的本地研究任务 worker。")
app.add_typer(worker_app, name="worker")
logger = get_logger(__name__)


@app.command("compare-s012")
def compare_s012() -> None:
    """Build the unified S0/S1/S2 web comparison from completed runs."""
    output = PROJECT_ROOT / "data" / "warehouse" / "reports" / "comparisons" / "report_s012_comparison.html"
    build_s012_comparison(PROJECT_ROOT / "data" / "warehouse" / "experiments.jsonl", output)
    typer.echo(f"S0/S1/S2 对照报告: {output}")


@app.command()
def factors() -> None:
    """Show the frozen factor profile used by the formal baseline."""
    typer.echo("正式基线：technical_baseline_7（固定七因子）")


@app.command("context-search")
def context_search(
    query: str = typer.Option(..., help="历史市场语境查询词。"),
    cutoff_date: str = typer.Option(..., help="只接受不晚于该日期发布的结果。"),
    max_results: int = typer.Option(3, min=1, max=3),
) -> None:
    """Search bounded historical context and append immutable evidence."""
    try:
        records = GoogleNewsRssSearcher(max_results=max_results).search(
            query, cutoff_date=cutoff_date,
        )
        path = PROJECT_ROOT / "data" / "raw" / "historical_context.jsonl"
        count = append_context(path, records)
    except Exception as exc:
        typer.echo(f"历史语境搜索失败，未写入归档: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"已写入 {count} 条历史语境记录: {path}")


@worker_app.command("create")
def worker_create(
    profile: str = typer.Option("s3"),
    llm_start: str | None = typer.Option(None),
    llm_end: str | None = typer.Option(None),
) -> None:
    manifest = JobManifest.create(profile, llm_start=llm_start, llm_end=llm_end)
    path = manifest.save(PROJECT_ROOT / "data" / "warehouse" / "jobs")
    typer.echo(f"研究任务已创建: {manifest.job_id}\n{path}")


@worker_app.command("run")
def worker_run(
    job_id: str = typer.Option(..., help="由 worker create 返回的 job_id"),
    tradability_mode: str = typer.Option("block"),
) -> None:
    root = PROJECT_ROOT / "data" / "warehouse" / "jobs"
    path = root / f"{job_id}.json"
    if not path.is_file():
        raise typer.BadParameter(f"找不到任务清单: {path}")
    manifest = JobManifest.load(path)
    result = run_job(manifest, root=root, tradability_mode=tradability_mode)
    if result is None:
        typer.echo(f"任务已完成，无需重复运行: {job_id}")
    else:
        typer.echo(f"任务完成: {job_id}\n报告: {result.consolidated_report_path}")


@app.command()
def run(
    profile: str = typer.Option("s0", help="m0, s0, s1, s2, s3, s3_next, s4, s4_n2, or all"),
    tradability_mode: str = typer.Option(
        "fail", help="fail=正式严格模式；block=缺证据订单保守阻断，仅用于诊断"
    ),
    llm_start: str | None = typer.Option(
        None, help="S3/S4短窗口起点，例如 2024-01-01；不填则完整回放"
    ),
    llm_end: str | None = typer.Option(
        None, help="S3/S4短窗口终点，例如 2025-12-31；不填则完整回放"
    ),
) -> None:
    """Run one frozen research profile, or all five profiles."""
    profiles = ("m0", "s0", "s1", "s2", "s3") if profile == "all" else (profile,)
    for selected_profile in profiles:
        logger.info("research profile starting: %s", selected_profile)
        result = run_pipeline(
            profile=selected_profile, tradability_mode=tradability_mode,
        llm_start=llm_start if selected_profile in {"s3", "s3_next", "s4", "s4_n2"} else None,
        llm_end=llm_end if selected_profile in {"s3", "s3_next", "s4", "s4_n2"} else None,
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

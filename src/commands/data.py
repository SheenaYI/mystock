"""`mystock data` command group: fetch, update, inspect local OHLCV data."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import duckdb
import typer

from common.logger import PROJECT_ROOT, get_logger, load_settings
from data.akshare import AKShareProvider
from data.downloader import Downloader
from data.storage import ParquetStorage

app = typer.Typer(help="Data acquisition commands.")
logger = get_logger(__name__)


def _raw_dir() -> Path:
    settings = load_settings()
    raw_path = settings.get("data", {}).get("raw_path", "data/raw")
    return PROJECT_ROOT / raw_path / "daily"


def _resolve_symbols(
    provider: AKShareProvider, universe: str, symbols: Optional[str]
) -> list[str]:
    if symbols:
        return [s.strip() for s in symbols.split(",") if s.strip()]
    if universe == "all":
        return provider.list_symbols()
    raise typer.BadParameter(
        f"unsupported universe: {universe!r} (only 'all' is supported)"
    )


@app.command()
def fetch(
    universe: str = typer.Option(
        "all", help="Symbol universe to fetch. Only 'all' is supported."
    ),
    symbols: Optional[str] = typer.Option(
        None,
        help=(
            "Comma-separated symbols, e.g. 600000.SH,000001.SZ. "
            "Overrides --universe."
        ),
    ),
    start_date: str = typer.Option(
        "1990-01-01", help="History start date (YYYY-MM-DD)."
    ),
    force: bool = typer.Option(
        False, help="Re-download symbols even if already stored locally."
    ),
) -> None:
    """Backfill daily OHLCV history for a universe or symbol list."""
    provider = AKShareProvider()
    storage = ParquetStorage(_raw_dir())
    target_symbols = _resolve_symbols(provider, universe, symbols)

    logger.info(
        "fetch starting: %d symbols, start_date=%s, force=%s",
        len(target_symbols), start_date, force,
    )
    summary = Downloader(provider, storage).run(
        target_symbols, start_date=start_date, force=force
    )

    ok, total = summary["succeeded"], summary["total"]
    typer.echo(f"完成: {ok}/{total} 成功, {len(summary['failed'])} 失败")
    if summary["failed"]:
        preview = ", ".join(summary["failed"][:20])
        suffix = " ..." if len(summary["failed"]) > 20 else ""
        typer.echo(f"失败列表: {preview}{suffix}")


@app.command()
def update(
    symbols: Optional[str] = typer.Option(
        None,
        help="Comma-separated symbols. Default: all symbols already stored.",
    ),
) -> None:
    """Incrementally update stored symbols with the latest trading days."""
    provider = AKShareProvider()
    storage = ParquetStorage(_raw_dir())
    target_symbols = (
        [s.strip() for s in symbols.split(",")]
        if symbols
        else storage.known_symbols()
    )

    if not target_symbols:
        typer.echo("没有已存储的数据，请先运行 `mystock data fetch`。")
        raise typer.Exit(code=1)

    logger.info("update starting: %d symbols", len(target_symbols))
    summary = Downloader(provider, storage).run(
        target_symbols, incremental=True
    )

    ok, total = summary["succeeded"], summary["total"]
    typer.echo(f"完成: {ok}/{total} 成功, {len(summary['failed'])} 失败")
    if summary["failed"]:
        preview = ", ".join(summary["failed"][:20])
        suffix = " ..." if len(summary["failed"]) > 20 else ""
        typer.echo(f"失败列表: {preview}{suffix}")


@app.command()
def status() -> None:
    """Show a summary of locally stored daily OHLCV data."""
    raw_dir = _raw_dir()
    if not raw_dir.exists() or not any(raw_dir.glob("*.parquet")):
        typer.echo("暂无数据，请先运行 `mystock data fetch`。")
        raise typer.Exit(code=1)

    con = duckdb.connect()
    symbols, min_date, max_date, rows = con.execute(
        f"""
        SELECT count(DISTINCT symbol), min(date), max(date), count(*)
        FROM read_parquet('{raw_dir.as_posix()}/*.parquet')
        """
    ).fetchone()
    parquet_files = raw_dir.glob("*.parquet")
    size_mb = sum(p.stat().st_size for p in parquet_files) / 1024 / 1024

    typer.echo(f"股票数: {symbols}")
    typer.echo(f"日期范围: {min_date} ~ {max_date}")
    typer.echo(f"总行数: {rows:,}")
    typer.echo(f"磁盘占用: {size_mb:.1f} MB")

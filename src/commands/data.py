"""`mystock data` command group: fetch, update, inspect local OHLCV data."""

from __future__ import annotations

from pathlib import Path
from typing import Optional
import json

import duckdb
import typer

from common.logger import PROJECT_ROOT, get_logger, load_settings
from data.akshare import AKShareProvider
from data.a_stock_data import AStockDataProvider
from data.downloader import Downloader
from data.manifest import build_ohlcv_manifest, write_ohlcv_manifest
from data.membership_import import convert_snapshot_archive
from data.storage import ParquetStorage
from data.joinquant_tradability import audit_tradability_coverage, import_export, merge_supplement, update_tradability
from data.repair import repair_symbols
from data.source_compare import compare_with_primary, normalize_ohlcv

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
def supplement(
    source: str = typer.Option(..., help="补充来源，目前支持 a-stock-data。"),
    symbols: str = typer.Option(..., help="Comma-separated symbols, e.g. 600000.SH,000001.SZ."),
    start_date: str = typer.Option(..., help="Supplement start date (YYYY-MM-DD)."),
    end_date: str = typer.Option(..., help="Supplement end date (YYYY-MM-DD)."),
) -> None:
    """Fetch a supplemental source, archive it, and report missing/conflicting rows.

    This command never writes into the existing AKShare OHLCV archive.  The
    comparison report is provider-neutral and can be reused by future sources.
    """
    if source != "a-stock-data":
        raise typer.BadParameter("目前只支持 --source a-stock-data")
    target = [item.strip() for item in symbols.split(",") if item.strip()]
    if not target:
        raise typer.BadParameter("--symbols 不能为空")
    supplement_root = PROJECT_ROOT / "data" / "raw" / "a_stock_data_raw" / "daily"
    report_root = PROJECT_ROOT / "data" / "warehouse" / "source_comparisons" / "a_stock_data"
    primary_root = _raw_dir()
    supplement_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    try:
        provider = AStockDataProvider()
    except Exception as exc:
        # Keep acquisition failure explicit and machine-readable.  In
        # particular, do not emit a traceback or touch the AKShare archive.
        summary = {
            "source": source,
            "requested": len(target),
            "archived": 0,
            "failed": [{"symbol": symbol, "error": repr(exc)} for symbol in target],
            "reports": [],
        }
        summary_path = report_root / "latest_summary.json"
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        typer.echo(f"补充源连接失败，未修改 AKShare；失败报告: {summary_path}", err=True)
        raise typer.Exit(code=1)
    reports = []
    failures = []
    for symbol in target:
        try:
            frame = normalize_ohlcv(
                provider.fetch(symbol, start_date=start_date, end_date=end_date),
                symbol=symbol,
            )
            if frame.empty:
                failures.append({"symbol": symbol, "error": "empty response"})
                continue
            frame.to_parquet(supplement_root / f"{symbol}.parquet", index=False, compression="zstd")
            reports.append(compare_with_primary(
                frame,
                primary_file=primary_root / f"{symbol}.parquet",
                report_root=report_root,
                source_name="a-stock-data",
            ))
        except Exception as exc:
            logger.warning("supplement failed symbol=%s: %s", symbol, exc)
            failures.append({"symbol": symbol, "error": repr(exc)})
    summary = {
        "source": source,
        "requested": len(target),
        "archived": len(reports),
        "failed": failures,
        "reports": reports,
    }
    summary_path = report_root / "latest_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"补充源原始数据目录: {supplement_root}")
    typer.echo(f"缺失/冲突报告: {summary_path}")
    typer.echo(f"完成: {len(reports)}/{len(target)} 成功, {len(failures)} 失败")


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


@app.command("manifest")
def manifest(
    price_adjustment: str = typer.Option(
        ..., help="明确声明数据口径：unadjusted、qfq 或 hfq。程序不会推断。"
    ),
    source_name: str = typer.Option("AKShare", help="数据来源名称。"),
    amount_unit: str = typer.Option("CNY", help="成交额单位。"),
) -> None:
    """Hash the existing archive and write its explicit OHLCV manifest."""
    raw_root = _raw_dir().parent
    payload = build_ohlcv_manifest(
        raw_root,
        price_adjustment=price_adjustment,
        source_name=source_name,
        amount_unit=amount_unit,
    )
    path = write_ohlcv_manifest(raw_root, payload)
    typer.echo(f"manifest 已写入: {path}")
    typer.echo(f"文件数: {payload['file_count']}; 哈希: {payload['files_sha256']}")


@app.command("membership-import")
def membership_import(
    source_root: Path = typer.Option(..., help="JoinQuant 年度成份股快照目录。"),
) -> None:
    """Import an archived snapshot directory into the strict loader format."""
    output_root = PROJECT_ROOT / "data" / "raw" / "membership" / "csi300"
    convert_snapshot_archive(source_root, output_root)
    typer.echo(f"历史成份股已写入: {output_root}")


@app.command("tradability-fetch")
def tradability_fetch(
    symbols: Optional[str] = typer.Option(None, help="Comma-separated symbols; default is historical CSI300 symbols."),
    start_date: str = typer.Option("2021-01-01", help="Start date (YYYY-MM-DD)."),
    end_date: str = typer.Option("2025-12-31", help="End date (YYYY-MM-DD)."),
    chunk_size: int = typer.Option(50, min=1, max=200, help="JoinQuant symbols per request."),
) -> None:
    """Fetch JoinQuant paused/limit fields without changing AKShare OHLCV."""
    if symbols:
        target = [item.strip() for item in symbols.split(",") if item.strip()]
    else:
        import pandas as pd
        membership_path = PROJECT_ROOT / "data" / "raw" / "membership" / "csi300" / "historical_index_membership.csv"
        membership = pd.read_csv(membership_path, dtype=str)
        target = sorted(membership["symbol"].dropna().unique().tolist())
    root = PROJECT_ROOT / "data" / "raw" / "tradability_joinquant"
    try:
        summary = update_tradability(target, start_date=start_date, end_date=end_date,
                                     root=root, chunk_size=chunk_size)
    except RuntimeError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"完成: {summary['succeeded']}/{summary['total']} 成功, {len(summary['failed'])} 只股票所属批次失败")
    typer.echo(f"数据目录: {root}")


@app.command("tradability-import")
def tradability_import(
    export_root: Path = typer.Option(..., help="聚宽下载的 jq_tradability_export 目录。"),
) -> None:
    """Verify and import the manual JoinQuant CSV export into Parquet."""
    canonical_root = PROJECT_ROOT / "data" / "raw" / "tradability_joinquant"
    try:
        manifest = import_export(export_root, canonical_root)
    except ValueError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"导入完成: {manifest['symbol_count']} 只股票, {manifest['row_count']} 条记录")
    typer.echo(f"规范目录: {canonical_root}")


@app.command("tradability-audit")
def tradability_audit(
    canonical_root: Path = typer.Option(
        PROJECT_ROOT / "data" / "raw" / "tradability_joinquant",
        help="规范化 JoinQuant 可成交档案目录。",
    ),
    membership_csv: Path = typer.Option(
        PROJECT_ROOT / "data" / "raw" / "membership" / "csi300" / "historical_index_membership.csv",
        help="历史沪深300成分股生效区间 CSV。",
    ),
    start_date: str = typer.Option("2021-01-01"),
    end_date: str = typer.Option("2025-12-31"),
) -> None:
    """Audit status-field coverage; incomplete evidence is not inferred."""
    report = audit_tradability_coverage(
        canonical_root, membership_csv, start_date=start_date, end_date=end_date
    )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "complete_for_membership_window":
        raise typer.Exit(code=2)


@app.command("tradability-merge-supplement")
def tradability_merge_supplement(
    supplement_root: Path = typer.Option(..., help="补充 CSV 所在目录。"),
) -> None:
    """Merge repaired JoinQuant rows with conflict detection."""
    canonical_root = PROJECT_ROOT / "data" / "raw" / "tradability_joinquant"
    try:
        summary = merge_supplement(supplement_root, canonical_root)
    except ValueError as exc:
        typer.echo(f"错误：{exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        f"补充完成: {summary['merged_rows']} 行, {summary['supplement_files']} 个文件; "
        f"跳过不完整行: {summary['skipped_incomplete_rows']}"
    )


@app.command("repair-missing")
def repair_missing(
    symbols: str = typer.Option(..., help="需要重抓的股票代码，逗号分隔。"),
    start_date: str = typer.Option(..., help="起始日期。"),
    end_date: str = typer.Option(..., help="结束日期。"),
) -> None:
    """Retry missing OHLCV rows without overwriting existing observations."""
    raw_root = PROJECT_ROOT / "data" / "raw" / "unadjusted_akshare"
    summary = repair_symbols(
        [item.strip() for item in symbols.split(",") if item.strip()],
        raw_root=raw_root, start_date=start_date, end_date=end_date,
    )
    typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))

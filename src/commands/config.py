"""Interactive local configuration helpers.

Secrets are written only to the project-local .env file.  The command never
prints secret values and updates only the keys it owns.
"""

from __future__ import annotations

import os
from getpass import getpass
from pathlib import Path

import typer

from common.logger import PROJECT_ROOT

app = typer.Typer(help="配置本地数据源和 LLM 凭据（不会显示密钥）。")


def _env_path() -> Path:
    return PROJECT_ROOT / ".env"


def _write_keys(updates: dict[str, str]) -> Path:
    path = _env_path()
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    replaced: set[str] = set()
    output: list[str] = []
    for line in existing:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            replaced.add(key)
        else:
            output.append(line)
    if output and output[-1].strip():
        output.append("")
    output.extend(f"{key}={value}" for key, value in updates.items() if key not in replaced)
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


@app.command("set-joinquant")
def set_joinquant() -> None:
    """Interactively save JoinQuant credentials for automated status downloads."""
    username = typer.prompt("聚宽账号", hide_input=False).strip()
    password = getpass("聚宽密码（输入时不显示）: ").strip()
    if not username or not password:
        raise typer.BadParameter("账号和密码都不能为空")
    path = _write_keys({"JQ_USERNAME": username, "JQ_PASSWORD": password})
    typer.echo(f"已写入 {path}（权限已设为仅当前用户可读写）")


@app.command("set-llm")
def set_llm() -> None:
    """Interactively save an OpenAI-compatible LLM configuration."""
    base_url = typer.prompt("LLM API Base URL").strip()
    api_key = getpass("LLM API Key（输入时不显示）: ").strip()
    model = typer.prompt("LLM Model").strip()
    if not base_url or not api_key or not model:
        raise typer.BadParameter("Base URL、API Key 和模型名都不能为空")
    path = _write_keys({
        "LLM_API_BASE_URL": base_url,
        "LLM_API_KEY": api_key,
        "LLM_MODEL": model,
    })
    typer.echo(f"已写入 {path}（权限已设为仅当前用户可读写）")


@app.command("status")
def status() -> None:
    """Show whether optional credentials exist, without revealing values."""
    from dotenv import dotenv_values

    values = dotenv_values(_env_path())
    for key in ("JQ_USERNAME", "JQ_PASSWORD", "LLM_API_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        configured = bool(str(values.get(key) or os.getenv(key) or "").strip())
        typer.echo(f"{key}: {'已配置' if configured else '未配置'}")

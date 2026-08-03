"""Logging setup, configured from config/settings.yaml."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"


def load_settings() -> dict[str, Any]:
    """Load config/settings.yaml as a dict. Returns {} if missing."""
    if not SETTINGS_PATH.exists():
        return {}
    with SETTINGS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_logger(name: str) -> logging.Logger:
    """Return a module logger configured with the level from settings.yaml."""
    settings = load_settings()
    level_name = settings.get("logging", {}).get("level", "INFO")
    level = getattr(logging, str(level_name).upper(), logging.INFO)

    root = logging.getLogger("mystock")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)

    return logging.getLogger(name)

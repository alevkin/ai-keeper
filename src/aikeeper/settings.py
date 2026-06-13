from __future__ import annotations

import os
from pathlib import Path


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def app_home() -> Path:
    return Path(os.environ.get("AIKEEPER_HOME", "~/.aikeeper")).expanduser()


def default_db_path() -> Path:
    return app_home() / "aikeeper.sqlite"


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()


def ensure_app_home() -> Path:
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    return home

from __future__ import annotations

import os
from pathlib import Path

try:
    import pwd
except ImportError:  # pragma: no cover - Windows fallback
    pwd = None


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def user_home() -> Path:
    if pwd is not None:
        try:
            home = pwd.getpwuid(os.getuid()).pw_dir
        except (KeyError, OSError):
            home = ""
        if home:
            return Path(home)
    return Path("~").expanduser()


def _configured_path(env_name: str, default_name: str) -> Path:
    configured = os.environ.get(env_name)
    if configured:
        return Path(configured).expanduser()
    return user_home() / default_name


def app_home() -> Path:
    return _configured_path("AIKEEPER_HOME", ".aikeeper")


def default_db_path() -> Path:
    return app_home() / "aikeeper.sqlite"


def budget_config_path() -> Path:
    return Path(os.environ.get("AIKEEPER_BUDGETS_FILE", app_home() / "budgets.toml")).expanduser()


def codex_home() -> Path:
    return _configured_path("CODEX_HOME", ".codex")


def claude_home() -> Path:
    return _configured_path("CLAUDE_HOME", ".claude")


def ensure_app_home() -> Path:
    home = app_home()
    home.mkdir(parents=True, exist_ok=True)
    return home

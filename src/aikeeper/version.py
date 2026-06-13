from __future__ import annotations

import subprocess
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _package_version() -> str:
    try:
        return version("aikeeper")
    except PackageNotFoundError:
        return "0.0.0"


def _run_git(repo_dir: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_dir,
            check=True,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def get_app_version(repo_dir: Path | str | None = None) -> dict[str, str | None]:
    root = Path(repo_dir).expanduser() if repo_dir else Path(__file__).resolve().parents[2]
    label = _run_git(root, "describe", "--tags", "--dirty", "--always") or _package_version()
    commit = _run_git(root, "rev-parse", "--short=7", "HEAD")
    return {"label": label, "commit": commit}

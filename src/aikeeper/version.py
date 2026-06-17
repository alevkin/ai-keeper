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


def get_update_channel_status(repo_dir: Path | str | None = None) -> dict[str, object]:
    root = Path(repo_dir).expanduser() if repo_dir else Path(__file__).resolve().parents[2]
    current = get_app_version(root)
    tags_raw = _run_git(root, "tag", "--list", "v*", "--sort=-v:refname") or ""
    latest_tag = next((line.strip() for line in tags_raw.splitlines() if line.strip()), None)
    current_commit = _run_git(root, "rev-parse", "HEAD")
    latest_commit = _run_git(root, "rev-list", "-n", "1", latest_tag) if latest_tag else None
    upgrade_available = bool(latest_tag and latest_commit and current_commit and latest_commit != current_commit)
    return {
        "current": current,
        "latest_tag": latest_tag,
        "latest_commit": latest_commit[:7] if latest_commit else None,
        "upgrade_available": upgrade_available,
        "upgrade_command": f"scripts/upgrade.sh --target {latest_tag}" if latest_tag else None,
    }

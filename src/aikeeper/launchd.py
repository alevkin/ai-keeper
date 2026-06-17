from __future__ import annotations

from dataclasses import dataclass
import os
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx

from aikeeper.settings import DEFAULT_HOST, DEFAULT_PORT, app_home, codex_home, default_db_path, ensure_app_home


LAUNCHD_LABEL = "com.aikeeper.daemon"


@dataclass(frozen=True)
class LaunchdResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


def project_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def default_launch_agent_path(label: str = LAUNCHD_LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def user_domain() -> str:
    return f"gui/{os.getuid()}"


def service_target(label: str = LAUNCHD_LABEL) -> str:
    return f"{user_domain()}/{label}"


def _uv_path() -> str:
    path = shutil.which("uv")
    if not path:
        raise RuntimeError("uv was not found on PATH; install uv or run service install from an environment with uv available")
    return path


def _daemon_command(
    *,
    host: str,
    port: int,
    db_path: Path,
    repo_dir: Path | None = None,
    uv_path: str | None = None,
) -> list[str]:
    root = repo_dir or project_root()
    if root:
        return [
            uv_path or _uv_path(),
            "--directory",
            str(root),
            "run",
            "aikeeper",
            "daemon",
            "start",
            "--host",
            host,
            "--port",
            str(port),
            "--db-path",
            str(db_path),
        ]
    executable = shutil.which("aikeeper")
    if not executable:
        raise RuntimeError("aikeeper executable was not found on PATH")
    return [
        executable,
        "daemon",
        "start",
        "--host",
        host,
        "--port",
        str(port),
        "--db-path",
        str(db_path),
    ]


def build_launch_agent_plist(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    db_path: Path | None = None,
    label: str = LAUNCHD_LABEL,
    repo_dir: Path | None = None,
    uv_path: str | None = None,
) -> dict[str, Any]:
    home = ensure_app_home()
    logs_dir = home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    db = (db_path or default_db_path()).expanduser()
    root = repo_dir or project_root() or Path.cwd()
    path_env = os.environ.get("PATH", "")
    if "/opt/homebrew/bin" not in path_env:
        path_env = f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:{path_env}"
    return {
        "Label": label,
        "ProgramArguments": _daemon_command(host=host, port=port, db_path=db, repo_dir=repo_dir, uv_path=uv_path),
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(logs_dir / "daemon.stdout.log"),
        "StandardErrorPath": str(logs_dir / "daemon.stderr.log"),
        "EnvironmentVariables": {
            "AIKEEPER_HOME": str(home),
            "CODEX_HOME": str(codex_home()),
            "PATH": path_env,
            "PYTHONUNBUFFERED": "1",
        },
    }


def write_launch_agent_plist(
    *,
    plist_path: Path | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    db_path: Path | None = None,
    label: str = LAUNCHD_LABEL,
    repo_dir: Path | None = None,
    uv_path: str | None = None,
) -> Path:
    target = (plist_path or default_launch_agent_path(label)).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    plist = build_launch_agent_plist(
        host=host,
        port=port,
        db_path=db_path,
        label=label,
        repo_dir=repo_dir,
        uv_path=uv_path,
    )
    with target.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=True)
    return target


def _run_launchctl(args: list[str], *, check: bool = False) -> LaunchdResult:
    command = ["launchctl", *args]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    launchd_result = LaunchdResult(command, result.returncode, result.stdout, result.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return launchd_result


def bootstrap_launch_agent(plist_path: Path, *, label: str = LAUNCHD_LABEL) -> None:
    _run_launchctl(["bootout", service_target(label)], check=False)
    _run_launchctl(["bootstrap", user_domain(), str(plist_path)], check=True)
    _run_launchctl(["enable", service_target(label)], check=False)
    _run_launchctl(["kickstart", "-k", service_target(label)], check=True)


def stop_launch_agent(*, label: str = LAUNCHD_LABEL) -> LaunchdResult:
    return _run_launchctl(["bootout", service_target(label)], check=False)


def start_launch_agent(*, label: str = LAUNCHD_LABEL) -> LaunchdResult:
    return _run_launchctl(["kickstart", "-k", service_target(label)], check=True)


def uninstall_launch_agent(*, plist_path: Path | None = None, label: str = LAUNCHD_LABEL) -> Path:
    target = (plist_path or default_launch_agent_path(label)).expanduser()
    stop_launch_agent(label=label)
    target.unlink(missing_ok=True)
    return target


def launch_agent_status(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    plist_path: Path | None = None,
    label: str = LAUNCHD_LABEL,
) -> dict[str, Any]:
    target = (plist_path or default_launch_agent_path(label)).expanduser()
    print_result = _run_launchctl(["print", service_target(label)], check=False)
    ping: dict[str, Any] = {"ok": False, "error": None}
    url = f"http://{host}:{port}"
    try:
        response = httpx.get(f"{url}/api/ping", timeout=0.6)
        data = response.json() if response.status_code == 200 else {}
        ping = {
            "ok": response.status_code == 200 and isinstance(data, dict) and data.get("service") == "aikeeper",
            "status_code": response.status_code,
            "version": data.get("version") if isinstance(data, dict) else None,
            "error": None,
        }
    except (httpx.HTTPError, ValueError) as exc:
        ping = {"ok": False, "error": str(exc)}
    return {
        "label": label,
        "plist_path": str(target),
        "plist_exists": target.exists(),
        "loaded": print_result.returncode == 0,
        "service_target": service_target(label),
        "url": url,
        "ping": ping,
        "launchctl_returncode": print_result.returncode,
        "launchctl_stdout": print_result.stdout[-4000:],
        "launchctl_stderr": print_result.stderr[-4000:],
    }

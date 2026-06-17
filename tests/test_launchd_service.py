import plistlib
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.launchd import LaunchdResult
from aikeeper.launchd import bootstrap_launch_agent
from aikeeper.launchd import build_launch_agent_plist
from aikeeper.launchd import default_launch_agent_path
from aikeeper.launchd import launch_agent_status
from aikeeper.launchd import write_launch_agent_plist


def test_build_launch_agent_plist_uses_keepalive_and_repo_command(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    codex_home = tmp_path / "codex"
    repo = tmp_path / "repo"
    db = tmp_path / "keeper.sqlite"
    repo.mkdir()
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    plist = build_launch_agent_plist(
        host="127.0.0.1",
        port=8766,
        db_path=db,
        repo_dir=repo,
        uv_path="/usr/local/bin/uv",
    )

    assert plist["Label"] == "com.aikeeper.daemon"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] is True
    assert plist["ProgramArguments"] == [
        "/usr/local/bin/uv",
        "--directory",
        str(repo),
        "run",
        "aikeeper",
        "daemon",
        "start",
        "--host",
        "127.0.0.1",
        "--port",
        "8766",
        "--db-path",
        str(db),
    ]
    assert plist["EnvironmentVariables"]["AIKEEPER_HOME"] == str(app_home)
    assert plist["EnvironmentVariables"]["CODEX_HOME"] == str(codex_home)
    assert plist["StandardOutPath"] == str(app_home / "logs" / "daemon.stdout.log")
    assert plist["StandardErrorPath"] == str(app_home / "logs" / "daemon.stderr.log")


def test_write_launch_agent_plist_outputs_valid_plist(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AIKEEPER_HOME", str(tmp_path / "home"))
    target = tmp_path / "com.aikeeper.daemon.plist"

    written = write_launch_agent_plist(
        plist_path=target,
        port=8766,
        db_path=tmp_path / "keeper.sqlite",
        repo_dir=tmp_path,
        uv_path="/usr/local/bin/uv",
    )

    assert written == target
    with target.open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["ProgramArguments"][9:11] == ["--port", "8766"]


def test_default_launch_agent_path_falls_back_when_standard_dir_is_not_writable(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "user"
    launch_agents = home / "Library" / "LaunchAgents"
    launch_agents.mkdir(parents=True)
    launch_agents.chmod(0o555)
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("AIKEEPER_HOME", str(tmp_path / "aikeeper"))

    try:
        path = default_launch_agent_path()
    finally:
        launch_agents.chmod(0o755)

    assert path == tmp_path / "aikeeper" / "LaunchAgents" / "com.aikeeper.daemon.plist"


def test_cli_service_install_writes_plist_without_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AIKEEPER_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("aikeeper.launchd._uv_path", lambda: "/usr/local/bin/uv")
    target = tmp_path / "service.plist"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "service",
            "install",
            "--port",
            "8766",
            "--plist-path",
            str(target),
            "--no-start",
        ],
    )

    assert result.exit_code == 0
    with target.open("rb") as handle:
        plist = plistlib.load(handle)
    assert plist["ProgramArguments"][9:11] == ["--port", "8766"]


def test_launch_agent_status_reports_ping(monkeypatch, tmp_path: Path) -> None:
    class LaunchctlResult:
        returncode = 0
        stdout = "loaded"
        stderr = ""

    class Response:
        status_code = 200

        def json(self):
            return {"ok": True, "service": "aikeeper", "version": {"label": "v-test"}}

    monkeypatch.setattr("aikeeper.launchd._run_launchctl", lambda *args, **kwargs: LaunchctlResult())
    monkeypatch.setattr("aikeeper.launchd.httpx.get", lambda *args, **kwargs: Response())

    status = launch_agent_status(port=8766, plist_path=tmp_path / "service.plist")

    assert status["loaded"] is True
    assert status["ping"]["ok"] is True
    assert status["ping"]["version"]["label"] == "v-test"


def test_bootstrap_launch_agent_retries_transient_bootstrap_io_error(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    bootstrap_attempts = 0

    def fake_run_launchctl(args: list[str], *, check: bool = False) -> LaunchdResult:
        nonlocal bootstrap_attempts
        calls.append(args)
        if args[0] == "bootstrap":
            bootstrap_attempts += 1
            if bootstrap_attempts < 4:
                result = LaunchdResult(["launchctl", *args], 5, "", "Bootstrap failed: 5: Input/output error")
                if check:
                    raise RuntimeError(result.stderr)
                return result
        return LaunchdResult(["launchctl", *args], 0, "", "")

    monkeypatch.setattr("aikeeper.launchd._run_launchctl", fake_run_launchctl)
    monkeypatch.setattr("aikeeper.launchd.time.sleep", lambda seconds: None)

    bootstrap_launch_agent(tmp_path / "service.plist")

    assert [call[0] for call in calls] == [
        "bootout",
        "bootstrap",
        "bootstrap",
        "bootstrap",
        "bootstrap",
        "enable",
        "kickstart",
    ]

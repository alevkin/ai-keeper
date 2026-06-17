import json
import zipfile
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.db import connect, init_db
from aikeeper.diagnostics import create_diagnostics_bundle


def test_create_diagnostics_bundle_writes_metadata_only_archive(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    db_path = app_home / "aikeeper.sqlite"
    app_home.mkdir()
    (app_home / "logs").mkdir()
    (app_home / "logs" / "daemon.stdout.log").write_text("AI Keeper listening\n", encoding="utf-8")
    (app_home / "logs" / "daemon.stderr.log").write_text("warning only\n", encoding="utf-8")
    with connect(db_path) as con:
        init_db(con)
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setattr(
        "aikeeper.diagnostics.launch_agent_status",
        lambda **kwargs: {
            "loaded": True,
            "ping": {"ok": True},
            "url": "http://127.0.0.1:8766",
            "plist_path": str(tmp_path / "service.plist"),
            "plist_exists": True,
        },
    )

    archive = create_diagnostics_bundle(db_path=db_path, output_dir=tmp_path, port=8766)

    assert archive.exists()
    with zipfile.ZipFile(archive) as package:
        names = set(package.namelist())
        assert {
            "manifest.json",
            "summary.md",
            "doctor.json",
            "privacy.json",
            "ingest_health.json",
            "service_status.json",
            "logs/daemon.stdout.tail.txt",
            "logs/daemon.stderr.tail.txt",
        } <= names
        manifest = json.loads(package.read("manifest.json"))
        summary = package.read("summary.md").decode("utf-8")
        joined = "\n".join(package.read(name).decode("utf-8", errors="replace") for name in names)

    assert manifest["metadata_only"] is True
    assert "No prompts, assistant messages, raw transcripts, or database files are included." in summary
    assert "secret_prompt" not in joined
    assert "aikeeper.sqlite" in summary
    assert "aikeeper.sqlite" not in names


def test_cli_diagnostics_bundle_outputs_archive_path(tmp_path: Path, monkeypatch) -> None:
    app_home = tmp_path / "home"
    db_path = app_home / "aikeeper.sqlite"
    out_dir = tmp_path / "bundles"
    monkeypatch.setenv("AIKEEPER_HOME", str(app_home))
    monkeypatch.setattr(
        "aikeeper.diagnostics.launch_agent_status",
        lambda **kwargs: {
            "loaded": False,
            "ping": {"ok": False},
            "url": "http://127.0.0.1:8766",
            "plist_path": str(tmp_path / "service.plist"),
            "plist_exists": False,
        },
    )
    with connect(db_path) as con:
        init_db(con)
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["diagnostics", "bundle", "--output-dir", str(out_dir), "--db-path", str(db_path), "--port", "8766", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert Path(payload["archive_path"]).exists()
    assert payload["metadata_only"] is True

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from aikeeper.db import connect, init_db
from aikeeper.version import get_update_channel_status
from aikeeper.web import create_app


REPO = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_release_script_dry_run_uses_local_artifacts_without_secrets(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "bash",
            str(REPO / "scripts" / "release.sh"),
            "--version",
            "v0.22.0",
            "--output-dir",
            str(tmp_path / "dist"),
            "--skip-tests",
            "--dry-run",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "AI Keeper release" in result.stdout
    assert "DRY RUN" in result.stdout
    assert "uv run aikeeper audit distribution --json" in result.stdout
    assert "scripts/package.sh --version v0.22.0" in result.stdout
    assert "scripts/sign-release.sh --dist-dir" in result.stdout
    assert "release-notes.md" in result.stdout
    assert "gh release" not in result.stdout
    assert "secrets." not in result.stdout


def test_repo_settings_checklist_documents_owner_actions() -> None:
    text = (REPO / "docs" / "repo-settings-checklist.md").read_text(encoding="utf-8")

    assert "Repository Settings Checklist" in text
    assert "default branch" in text
    assert "branch protection" in text
    assert "Actions permissions" in text
    assert "owner action" in text
    assert "personal account" in text


def test_update_channel_status_compares_current_commit_to_latest_tag(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "AI Keeper Test")
    (tmp_path / "README.md").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "one")
    first = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    _git(tmp_path, "tag", "v1.0.0")
    (tmp_path / "README.md").write_text("two\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "two")
    _git(tmp_path, "tag", "v1.1.0")
    _git(tmp_path, "checkout", first)

    status = get_update_channel_status(tmp_path)

    assert status["current"]["label"] == "v1.0.0"
    assert status["latest_tag"] == "v1.1.0"
    assert status["upgrade_available"] is True
    assert status["upgrade_command"] == "scripts/upgrade.sh --target v1.1.0"


def test_system_page_renders_update_channel(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    with connect(db_path) as con:
        init_db(con)
    client = TestClient(create_app(db_path=db_path))

    page = client.get("/system")

    assert page.status_code == 200
    assert "Update Channel" in page.text
    assert "Latest tag" in page.text
    assert "Upgrade command" in page.text


def test_install_script_reports_preflight_in_dry_run() -> None:
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "install.sh"), "--dry-run", "--port", "8766"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Preflight" in result.stdout
    assert "uv: ok" in result.stdout
    assert "Platform:" in result.stdout
    assert "AI Keeper dashboard: http://127.0.0.1:8766" in result.stdout
    assert "+ open http://127.0.0.1:8766" in result.stdout

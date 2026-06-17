import json
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.distribution import audit_distribution_readiness


REPO = Path(__file__).resolve().parents[1]


def test_gitignore_excludes_editor_workspace_state() -> None:
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".vscode/" in ignored


def test_distribution_audit_passes_current_repo_without_company_or_project_coupling() -> None:
    result = audit_distribution_readiness(REPO)

    assert result["status"] == "pass"
    assert result["project_agnostic"] is True
    assert result["company_agnostic"] is True
    assert result["metadata_only"] is True
    assert result["findings"] == []
    assert result["checks"]["tracked_files"] > 0
    assert "scripts/package.sh" in result["checks"]["required_files"]


def test_distribution_audit_flags_private_project_and_company_markers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    private_user = "Andrei" + "_Levkin"
    private_path = "/Users/" + private_user + "/w/" + "tfs/" + "ng-" + "workspace"
    company_marker = "private-company" + "private-company.com"
    key_marker = "pers_" + "alevkin_260617"
    (repo / "pyproject.toml").write_text("[project]\nname = 'aikeeper'\n", encoding="utf-8")
    (repo / "README.md").write_text(f"Project path {private_path}\n", encoding="utf-8")
    (repo / "notes.md").write_text(f"{company_marker} and {key_marker}\n", encoding="utf-8")

    result = audit_distribution_readiness(repo)
    serialized = json.dumps(result)

    assert result["status"] == "fail"
    assert result["project_agnostic"] is False
    assert result["company_agnostic"] is False
    assert "README.md" in serialized
    assert "notes.md" in serialized
    assert private_user not in serialized
    assert company_marker not in serialized
    assert key_marker not in serialized


def test_cli_distribution_audit_emits_json() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["audit", "distribution", "--repo-root", str(REPO), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert payload["company_agnostic"] is True

import hashlib
import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from aikeeper.cli import app
from aikeeper.public_release import evaluate_public_release_gate


REPO = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _write_release_artifacts(dist: Path, tag: str) -> None:
    dist.mkdir()
    archive = dist / f"aikeeper-{tag}.tar.gz"
    archive.write_bytes(b"release archive")
    archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    (dist / f"{archive.name}.sha256").write_text(f"{archive_hash}  {archive.name}\n", encoding="utf-8")
    manifest = {
        "version": tag,
        "archive": archive.name,
        "sha256": archive_hash,
        "metadata_only": True,
    }
    (dist / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (dist / "SIGNING.md").write_text("Verify release checksums.\n", encoding="utf-8")
    checksum_lines = []
    for path in sorted(dist.iterdir()):
        if path.name == "CHECKSUMS.txt":
            continue
        checksum_lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    (dist / "CHECKSUMS.txt").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def _write_minimal_release_repo(repo: Path, tag: str = "v1.2.3") -> None:
    version = tag.removeprefix("v")
    required_files = [
        "README.md",
        "BACKLOG.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "PRIVACY.md",
        "docs/public-release-checklist.md",
        "docs/repo-settings-checklist.md",
        "docs/release-verification.md",
        "docs/github-ops-status.md",
        "docs/public-release-gate.md",
        "docs/release-upload-design.md",
        "uv.lock",
        "scripts/generate-changelog.py",
        "scripts/install.sh",
        "scripts/package.sh",
        "scripts/public-release-gate.sh",
        "scripts/release.sh",
        "scripts/sign-release.sh",
        "scripts/update-version.py",
        "scripts/upgrade.sh",
        "scripts/rollback.sh",
        "packaging/README.md",
        "packaging/macos/README.md",
        "packaging/macos/dmg/Aikeeper Installer.command",
        "packaging/macos/dmg/README.md",
        "packaging/windows/README.md",
        "packaging/windows/install-service.ps1",
    ]
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "packaging").mkdir()
    (repo / "scripts").mkdir()
    for rel_path in required_files:
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{rel_path}\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "aikeeper"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (repo / "packaging" / "manifest.json").write_text(
        json.dumps({"version": version, "local_only": True, "metadata_only": True}, indent=2) + "\n",
        encoding="utf-8",
    )
    (repo / "CHANGELOG.md").write_text(f"# Changelog\n\n## {tag}\n\n- Test release.\n", encoding="utf-8")
    (repo / ".github" / "workflows" / "ci.yml").write_text(
        "name: CI\npermissions:\n  contents: read\n",
        encoding="utf-8",
    )
    (repo / ".github" / "workflows" / "release.yml").write_text(
        "name: Release\npermissions:\n  contents: write\nsteps:\n  - run: gh release create \"$TAG\"\n",
        encoding="utf-8",
    )
    (repo / ".github" / "workflows" / "public-release-gate.yml").write_text(
        "name: Public Release Gate\nworkflow_dispatch:\npermissions:\n  contents: read\n  actions: read\n"
        "steps:\n  - run: bash scripts/public-release-gate.sh --version v1.2.3 --online\n",
        encoding="utf-8",
    )
    _write_release_artifacts(repo / "dist", tag)
    _git(repo, "init")
    _git(repo, "config", "user.email", "alevkin@gmail.com")
    _git(repo, "config", "user.name", "Andrei Levkin")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore(release): test")
    _git(repo, "tag", "-a", tag, "-m", tag)


def test_public_release_gate_passes_for_complete_local_release(tmp_path: Path) -> None:
    _write_minimal_release_repo(tmp_path)

    result = evaluate_public_release_gate(
        repo_root=tmp_path,
        db_path=tmp_path / "keeper.sqlite",
        dist_dir=tmp_path / "dist",
        tag="v1.2.3",
        allow_dirty=False,
        privacy_result={"status": "pass", "metadata_only": True, "findings": []},
        distribution_result={
            "status": "pass",
            "project_agnostic": True,
            "company_agnostic": True,
            "metadata_only": True,
            "local_only": True,
            "findings": [],
        },
    )

    assert result["status"] == "pass"
    assert result["release_ready"] is True
    assert result["tag"] == "v1.2.3"
    assert {check["name"] for check in result["checks"]} >= {
        "privacy_audit",
        "distribution_audit",
        "git_worktree_clean",
        "git_author_history",
        "changelog",
        "release_artifacts",
        "workflow_readiness",
    }


def test_public_release_gate_fails_when_changelog_is_missing_tag(tmp_path: Path) -> None:
    _write_minimal_release_repo(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")

    result = evaluate_public_release_gate(
        repo_root=tmp_path,
        db_path=tmp_path / "keeper.sqlite",
        dist_dir=tmp_path / "dist",
        tag="v1.2.3",
        allow_dirty=True,
        privacy_result={"status": "pass", "metadata_only": True, "findings": []},
        distribution_result={
            "status": "pass",
            "project_agnostic": True,
            "company_agnostic": True,
            "metadata_only": True,
            "local_only": True,
            "findings": [],
        },
    )

    assert result["status"] == "fail"
    assert any(check["name"] == "changelog" and check["status"] == "fail" for check in result["checks"])


def test_cli_public_release_gate_emits_json_for_current_release(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_release_repo(repo, "v1.2.3")

    result = CliRunner().invoke(
        app,
        [
            "audit",
            "public-release",
            "--repo-root",
            str(repo),
            "--db-path",
            str(tmp_path / "keeper.sqlite"),
            "--dist-dir",
            str(repo / "dist"),
            "--tag",
            "v1.2.3",
            "--allow-dirty",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["status"] == "pass"
    assert payload["release_ready"] is True

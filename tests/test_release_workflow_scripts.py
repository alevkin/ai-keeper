import json
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _copy_script(name: str, target: Path) -> Path:
    script = target / name
    script.write_text((REPO / "scripts" / name).read_text(encoding="utf-8"), encoding="utf-8")
    return script


def test_update_version_updates_package_metadata_and_manifest(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "aikeeper"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging" / "manifest.json").write_text(
        json.dumps({"version": "0.1.0"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "aikeeper"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    script = _copy_script("update-version.py", tmp_path)

    result = subprocess.run(
        ["python", str(script), "v1.2.3"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'version = "1.2.3"' in (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'version = "1.2.3"' in (tmp_path / "uv.lock").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "packaging" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.2.3"


def test_generate_changelog_prepends_new_version_section(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "AI Keeper Test")
    (tmp_path / "README.md").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "feat: initial tracker")
    _git(tmp_path, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    (tmp_path / "README.md").write_text("two\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "fix: correct dashboard link")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## v1.0.0\n\n- Initial.\n", encoding="utf-8")
    script = _copy_script("generate-changelog.py", tmp_path)

    result = subprocess.run(
        ["python", str(script), "--version", "v1.0.1", "--previous-tag", "v1.0.0"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.startswith("# Changelog\n\n## v1.0.1\n\n- fix: correct dashboard link")
    assert "## v1.0.0" in changelog
    assert "Release notes: CHANGELOG.md" in result.stdout

    second = subprocess.run(
        ["python", str(script), "--version", "v1.0.1", "--previous-tag", "v1.0.0"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert second.returncode == 0, second.stderr
    assert (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8").count("## v1.0.1") == 1

import subprocess
from pathlib import Path

from aikeeper.version import get_app_version


def test_get_app_version_prefers_git_tag(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "AI Keeper Test"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "tag", "-a", "v1.2.3", "-m", "release"], cwd=tmp_path, check=True)

    version = get_app_version(repo_dir=tmp_path)

    assert version["label"] == "v1.2.3"
    assert len(version["commit"]) == 7


def test_get_app_version_defaults_to_package_version(monkeypatch) -> None:
    monkeypatch.setattr("aikeeper.version._package_version", lambda: "0.30.5")

    def fake_git(_repo_dir: Path, *args: str) -> str | None:
        if args[0] == "describe":
            return "6.0.2"
        if args[0] == "rev-parse":
            return "6861449"
        return None

    monkeypatch.setattr("aikeeper.version._run_git", fake_git)

    version = get_app_version()

    assert version == {"label": "0.30.5", "commit": "6861449"}

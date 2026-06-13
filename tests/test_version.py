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

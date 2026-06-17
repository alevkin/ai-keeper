import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_install_git_hooks_writes_local_pre_commit_and_pre_push(tmp_path: Path) -> None:
    hooks_dir = tmp_path / "hooks"

    result = subprocess.run(
        [
            "bash",
            str(REPO / "scripts" / "install-git-hooks.sh"),
            "--repo-root",
            str(REPO),
            "--hooks-dir",
            str(hooks_dir),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    pre_commit = hooks_dir / "pre-commit"
    pre_push = hooks_dir / "pre-push"
    assert pre_commit.exists()
    assert pre_push.exists()
    assert "aikeeper audit distribution --json" in pre_commit.read_text(encoding="utf-8")
    assert "aikeeper audit distribution --json" in pre_push.read_text(encoding="utf-8")
    assert "load_private_marker_rules" in pre_push.read_text(encoding="utf-8")
    assert "AIKEEPER_PRIVATE_MARKERS" in pre_commit.read_text(encoding="utf-8")
    assert "AIKEEPER_PRIVATE_MARKERS" in pre_push.read_text(encoding="utf-8")

    assert subprocess.run(["bash", "-n", str(pre_commit)], check=False).returncode == 0
    assert subprocess.run(["bash", "-n", str(pre_push)], check=False).returncode == 0

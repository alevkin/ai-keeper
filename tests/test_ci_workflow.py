from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_github_ci_workflow_runs_metadata_only_release_checks() -> None:
    workflow = REPO / ".github" / "workflows" / "ci.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "name: CI" in text
    assert "contents: read" in text
    assert "actions/checkout@v4" in text
    assert "actions/setup-python@v5" in text
    assert 'python-version: "3.13"' in text
    assert "python -m pip install uv" in text
    assert "uv run pytest -q" in text
    assert "uv run aikeeper audit privacy --json" in text
    assert "uv run aikeeper audit distribution --json" in text
    assert "bash scripts/package.sh --version ci-${{ github.sha }} --output-dir dist" in text
    assert "bash scripts/sign-release.sh --dist-dir dist --signer none" in text
    assert "shasum -a 256 -c CHECKSUMS.txt" in text
    assert "ruby -c dist/homebrew/aikeeper.rb" in text
    assert "ruby -c dist/homebrew-tap/Formula/aikeeper.rb" in text
    assert "secrets." not in text


def test_github_release_workflow_autogenerates_changelog_and_release_artifacts() -> None:
    workflow = REPO / ".github" / "workflows" / "release.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "name: Release" in text
    assert "branches: [main]" in text
    assert "contents: write" in text
    assert "fetch-depth: 0" in text
    assert "chore(release):" in text
    assert "Calculate next version" in text
    assert "BREAKING CHANGE" in text
    assert "feat" in text
    assert "fix|perf|refactor|chore" in text
    assert "python scripts/update-version.py" in text
    assert "python scripts/generate-changelog.py" in text
    assert "git add CHANGELOG.md pyproject.toml packaging/manifest.json" in text
    assert 'git tag -a "$TAG"' in text
    assert "bash scripts/release.sh --version \"$TAG\"" in text
    assert "gh release create \"$TAG\"" in text
    assert "dist/aikeeper-${TAG}.tar.gz" in text
    assert "TEAMS_WEBHOOK_URL" not in text
    assert "secrets." not in text


def test_public_release_gate_workflow_runs_manually_with_read_only_permissions() -> None:
    workflow = REPO / ".github" / "workflows" / "public-release-gate.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "name: Public Release Gate" in text
    assert "workflow_dispatch" in text
    assert "contents: read" in text
    assert "actions: read" in text
    assert "fetch-depth: 0" in text
    assert "scripts/public-release-gate.sh" in text
    assert "--online" in text
    assert "secrets." not in text

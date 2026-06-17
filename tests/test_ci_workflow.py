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

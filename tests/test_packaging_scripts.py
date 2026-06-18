import json
import os
import tarfile
import subprocess
import tomllib
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    with (REPO / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def test_install_upgrade_and_rollback_scripts_support_dry_run() -> None:
    scripts = {
        "install": REPO / "scripts" / "install.sh",
        "upgrade": REPO / "scripts" / "upgrade.sh",
        "rollback": REPO / "scripts" / "rollback.sh",
    }

    for name, script in scripts.items():
        result = subprocess.run(
            ["bash", str(script), "--dry-run", "--port", "8766"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "AIKEEPER_TEST_ROLLBACK_TARGET": "v0.12.0"},
        )
        assert result.returncode == 0, result.stderr
        assert "AI Keeper" in result.stdout
        assert "DRY RUN" in result.stdout
        assert "uv run aikeeper" not in result.stdout
        if name != "rollback":
            assert "aikeeper install all --port 8766" in result.stdout
            assert "aikeeper doctor --port 8766" in result.stdout
        if name == "upgrade":
            assert "Rollback ref:" in result.stdout
            assert "Rollback ref: v0.12.0-dirty" not in result.stdout


def test_packaging_manifest_documents_light_packaging_surface() -> None:
    manifest_path = REPO / "packaging" / "manifest.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "AI Keeper"
    assert manifest["version"] == _project_version()
    assert manifest["local_only"] is True
    assert manifest["metadata_only"] is True
    assert manifest["scripts"]["install"] == "scripts/install.sh"
    assert manifest["scripts"]["install_git_hooks"] == "scripts/install-git-hooks.sh"
    assert manifest["scripts"]["package"] == "scripts/package.sh"
    assert manifest["scripts"]["publish"] == "scripts/publish.sh"
    assert manifest["scripts"]["publish_homebrew_tap"] == "scripts/publish-homebrew-tap.sh"
    assert manifest["scripts"]["public_release_gate"] == "scripts/public-release-gate.sh"
    assert manifest["scripts"]["release"] == "scripts/release.sh"
    assert manifest["scripts"]["sign"] == "scripts/sign-release.sh"
    assert manifest["targets"]["source_archive"] == "dist/aikeeper-<version>.tar.gz"
    assert manifest["targets"]["homebrew_formula"] == "dist/homebrew/aikeeper.rb"
    assert manifest["targets"]["homebrew_tap_formula"] == "dist/homebrew-tap/Formula/aikeeper.rb"
    assert manifest["targets"]["homebrew_tap_publish"] == "scripts/publish-homebrew-tap.sh"
    assert manifest["targets"]["checksums"] == "dist/CHECKSUMS.txt"
    assert manifest["targets"]["ci_workflow"] == ".github/workflows/ci.yml"
    assert manifest["targets"]["release_workflow"] == ".github/workflows/release.yml"
    assert manifest["targets"]["public_release_gate_workflow"] == ".github/workflows/public-release-gate.yml"
    assert manifest["targets"]["pages_workflow"] == ".github/workflows/pages.yml"
    assert manifest["targets"]["landing_page"] == "docs/index.html"
    assert manifest["targets"]["landing_styles"] == "docs/styles.css"
    assert manifest["targets"]["landing_dashboard_preview"] == "docs/assets/dashboard-preview.svg"
    assert manifest["targets"]["landing_social_preview"] == "docs/assets/social-preview.png"
    assert manifest["targets"]["landing_robots"] == "docs/robots.txt"
    assert manifest["targets"]["landing_sitemap"] == "docs/sitemap.xml"
    assert manifest["targets"]["user_guide"] == "docs/user-guide.md"
    assert manifest["targets"]["release_notes"] == "dist/release-notes.md"
    assert manifest["targets"]["changelog"] == "CHANGELOG.md"
    assert manifest["targets"]["github_ops_status"] == "docs/github-ops-status.md"
    assert manifest["targets"]["public_release_gate_doc"] == "docs/public-release-gate.md"
    assert manifest["targets"]["release_upload_design"] == "docs/release-upload-design.md"
    assert manifest["targets"]["repo_settings_checklist"] == "docs/repo-settings-checklist.md"
    assert manifest["targets"]["version_updater"] == "scripts/update-version.py"
    assert manifest["targets"]["changelog_generator"] == "scripts/generate-changelog.py"
    assert manifest["targets"]["public_release_gate"] == "scripts/public-release-gate.sh"
    assert manifest["targets"]["local_git_hooks"] == "scripts/install-git-hooks.sh"
    assert manifest["repository"]["url"] == "git@github.com:alevkin/ai-keeper.git"
    assert manifest["repository"]["visibility"] == "private"
    assert manifest["homebrew_tap"]["repository"] == "alevkin/homebrew-tap"
    assert manifest["homebrew_tap"]["formula"] == "Formula/aikeeper.rb"
    assert manifest["homebrew_tap"]["install"] == "brew install alevkin/tap/aikeeper"
    assert manifest["signing"]["default"] == "cosign-keyless"
    assert manifest["signing"]["issuer"] == "https://token.actions.githubusercontent.com"
    assert manifest["signing"]["identity"] == (
        "https://github.com/alevkin/ai-keeper/.github/workflows/release.yml@refs/heads/main"
    )
    assert "dist/CHECKSUMS.txt.sigstore.json" in manifest["signing"]["bundles"]
    assert manifest["future_targets"] == [
        "public-visibility-switch",
        "brew-install-smoke-test",
        "signed-macos-installer",
    ]


def test_package_script_builds_release_archive_manifest_and_formula(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.22.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    archive = output_dir / "aikeeper-v0.22.0.tar.gz"
    checksum = output_dir / "aikeeper-v0.22.0.tar.gz.sha256"
    checksums = output_dir / "CHECKSUMS.txt"
    manifest_path = output_dir / "release-manifest.json"
    formula = output_dir / "homebrew" / "aikeeper.rb"
    tap_formula = output_dir / "homebrew-tap" / "Formula" / "aikeeper.rb"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result.returncode == 0, result.stderr
    assert archive.exists()
    assert checksum.exists()
    assert formula.exists()
    assert manifest["version"] == "v0.22.0"
    assert manifest["archive"] == archive.name
    assert len(manifest["sha256"]) == 64
    assert manifest["metadata_only"] is True
    assert checksums.exists()
    assert manifest["checksums"] == checksums.name
    formula_text = formula.read_text(encoding="utf-8")
    tap_formula_text = tap_formula.read_text(encoding="utf-8")
    assert 'desc "Local-only AI token usage daemon and dashboard"' in formula_text
    assert 'desc "Local-only AI token usage daemon and dashboard"' in tap_formula_text
    assert "file://" in formula_text
    assert 'homepage "https://github.com/alevkin/ai-keeper"' in formula_text
    assert 'url "https://github.com/alevkin/ai-keeper/releases/download/v0.22.0/aikeeper-v0.22.0.tar.gz"' in tap_formula_text
    assert "file://" not in tap_formula_text
    assert manifest["sha256"] in formula_text
    assert manifest["sha256"] in tap_formula_text
    assert 'depends_on "uv"' not in formula_text
    assert 'resource "uv"' in formula_text
    assert "uv-aarch64-apple-darwin.tar.gz" in formula_text
    assert "uv-x86_64-apple-darwin.tar.gz" in formula_text
    assert "uv-aarch64-unknown-linux-gnu.tar.gz" in formula_text
    assert "uv-x86_64-unknown-linux-gnu.tar.gz" in formula_text
    assert 'raise "uv resource did not contain uv or uvx" if uv_files.empty?' in formula_text
    assert 'export PATH="#{libexec}/vendor/uv:$PATH"' in formula_text
    assert "aikeeper-install" in formula_text
    assert '(bin/"aikeeper").write' in formula_text
    assert 'exec "#{libexec}/.venv/bin/aikeeper" "$@"' in formula_text
    assert "aikeeper-install-git-hooks" in formula_text
    assert "aikeeper-upgrade" in formula_text

    repeat_dir = tmp_path / "dist-repeat"
    repeat = subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.22.0", "--output-dir", str(repeat_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    repeat_manifest = json.loads((repeat_dir / "release-manifest.json").read_text(encoding="utf-8"))

    assert repeat.returncode == 0, repeat.stderr
    assert repeat_manifest["sha256"] == manifest["sha256"]
    assert "aikeeper-rollback" in formula_text
    assert "aikeeper-publish" in formula_text
    assert "aikeeper-sign" in formula_text
    assert "aikeeper-release" in formula_text
    assert "aikeeper-public-release-gate" in formula_text
    assert 'inreplace libexec/"pyproject.toml", \'readme = "README.md"\', \'readme = "../README.md"\'' in formula_text
    assert "def post_install" not in formula_text
    assert 'ENV["AIKEEPER_SKIP_AUTO_INSTALL"]' not in formula_text
    assert 'ENV.fetch("AIKEEPER_PORT", "8766")' not in formula_text
    assert 'system bin/"aikeeper-install", "--port"' not in formula_text
    assert "Run setup after install:" in formula_text
    assert "aikeeper-install --port 8766" in formula_text
    assert "Custom port: aikeeper-install --port 8770" in formula_text
    assert "Doctor: aikeeper doctor --port 8766" in formula_text

    with tarfile.open(archive, "r:gz") as package:
        names = package.getnames()

    assert "aikeeper-v0.22.0/docs/user-guide.md" in names
    assert "aikeeper-v0.22.0/scripts/install.sh" in names
    assert "aikeeper-v0.22.0/scripts/install-git-hooks.sh" in names
    assert "aikeeper-v0.22.0/scripts/public-release-gate.sh" in names
    assert "aikeeper-v0.22.0/scripts/release.sh" in names
    assert "aikeeper-v0.22.0/scripts/sign-release.sh" in names
    assert "aikeeper-v0.22.0/pyproject.toml" in names
    assert not any("/.git/" in name or "/.venv/" in name or "/.vscode/" in name for name in names)
    assert not any(name.endswith("aikeeper.sqlite") or "/sessions/" in name for name in names)


def test_publish_homebrew_tap_script_scaffolds_tap_without_push(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    tap_dir = tmp_path / "homebrew-tap"

    subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.24.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        [
            "bash",
            str(REPO / "scripts" / "publish-homebrew-tap.sh"),
            "--version",
            "v0.24.0",
            "--dist-dir",
            str(output_dir),
            "--tap-dir",
            str(tap_dir),
            "--no-push",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    formula = tap_dir / "Formula" / "aikeeper.rb"
    readme = tap_dir / "README.md"
    assert formula.exists()
    assert readme.exists()
    assert "brew install alevkin/tap/aikeeper" in readme.read_text(encoding="utf-8")
    assert "https://github.com/alevkin/ai-keeper/releases/download/v0.24.0" in formula.read_text(encoding="utf-8")
    assert "Push: skipped" in result.stdout

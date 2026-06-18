import json
import subprocess
import tomllib
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _project_version() -> str:
    with (REPO / "pyproject.toml").open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def test_public_release_hygiene_documents_are_present_and_metadata_first() -> None:
    required_docs = {
        "LICENSE": ["MIT License", "Andrei Levkin"],
        "SECURITY.md": ["Supported Versions", "metadata-only", "private disclosure"],
        "CONTRIBUTING.md": ["metadata-only", "tests", "distribution audit"],
        "PRIVACY.md": ["does not store prompts", "transcript contents", "local-only"],
        "docs/public-release-checklist.md": ["Public Release Checklist", "default branch", "license"],
        "CHANGELOG.md": ["Changelog", "release.yml"],
    }

    for rel_path, expected_fragments in required_docs.items():
        text = (REPO / rel_path).read_text(encoding="utf-8")
        for fragment in expected_fragments:
            assert fragment in text


def test_packaging_manifest_tracks_distribution_prep_wave_targets() -> None:
    manifest = json.loads((REPO / "packaging" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["version"] == _project_version()
    assert manifest["scripts"]["sign"] == "scripts/sign-release.sh"
    assert manifest["targets"]["checksums"] == "dist/CHECKSUMS.txt"
    assert manifest["targets"]["homebrew_tap_formula"] == "dist/homebrew-tap/Formula/aikeeper.rb"
    assert manifest["targets"]["homebrew_tap_publish"] == "scripts/publish-homebrew-tap.sh"
    assert manifest["targets"]["ci_workflow"] == ".github/workflows/ci.yml"
    assert manifest["targets"]["release_workflow"] == ".github/workflows/release.yml"
    assert manifest["targets"]["public_release_gate_workflow"] == ".github/workflows/public-release-gate.yml"
    assert manifest["targets"]["pages_workflow"] == ".github/workflows/pages.yml"
    assert manifest["targets"]["landing_page"] == "docs/index.html"
    assert manifest["targets"]["landing_styles"] == "docs/styles.css"
    assert manifest["targets"]["landing_dashboard_preview"] == "docs/assets/dashboard-preview.svg"
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
    assert manifest["targets"]["issue_template_config"] == ".github/ISSUE_TEMPLATE/config.yml"
    assert manifest["targets"]["bug_report_template"] == ".github/ISSUE_TEMPLATE/bug_report.yml"
    assert manifest["targets"]["feature_request_template"] == ".github/ISSUE_TEMPLATE/feature_request.yml"
    assert manifest["targets"]["macos_dmg_wrapper"] == "packaging/macos/dmg/Aikeeper Installer.command"
    assert manifest["homebrew_tap"]["repository"] == "alevkin/homebrew-tap"
    assert manifest["homebrew_tap"]["install"] == "brew install alevkin/tap/aikeeper"
    assert manifest["future_targets"] == [
        "public-visibility-switch",
        "brew-install-smoke-test",
        "signed-macos-installer",
    ]


def test_package_script_writes_tap_formula_and_checksum_index(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.22.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    archive = output_dir / "aikeeper-v0.22.0.tar.gz"
    checksums = output_dir / "CHECKSUMS.txt"
    tap_formula = output_dir / "homebrew-tap" / "Formula" / "aikeeper.rb"
    manifest = json.loads((output_dir / "release-manifest.json").read_text(encoding="utf-8"))

    assert archive.exists()
    assert checksums.exists()
    assert f"  {archive.name}" in checksums.read_text(encoding="utf-8")
    assert tap_formula.exists()
    tap_formula_text = tap_formula.read_text(encoding="utf-8")
    assert 'homepage "https://github.com/alevkin/ai-keeper"' in tap_formula_text
    assert 'url "https://github.com/alevkin/ai-keeper/releases/download/v0.22.0/aikeeper-v0.22.0.tar.gz"' in tap_formula_text
    assert manifest["checksums"] == checksums.name
    assert manifest["homebrew_tap_formula"] == str(tap_formula)
    assert manifest["homebrew_tap"]["install"] == "brew install alevkin/tap/aikeeper"
    assert manifest["signing"]["default"] == "cosign-keyless"
    assert manifest["signing"]["bundles"] == [
        f"{archive.name}.sigstore.json",
        "CHECKSUMS.txt.sigstore.json",
        "release-manifest.json.sigstore.json",
    ]
    assert manifest["signing"]["optional"] == ["minisign"]


def test_sign_release_script_generates_verification_materials(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.22.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "sign-release.sh"), "--dist-dir", str(output_dir), "--signer", "none"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "AI Keeper release verification" in result.stdout
    assert (output_dir / "CHECKSUMS.txt").exists()
    signing_doc = output_dir / "SIGNING.md"
    assert signing_doc.exists()
    assert "shasum -a 256 -c CHECKSUMS.txt" in signing_doc.read_text(encoding="utf-8")


def test_sign_release_dry_run_shows_optional_signature_command(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    output_dir.mkdir()
    (output_dir / "aikeeper-v0.22.0.tar.gz").write_text("package", encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            str(REPO / "scripts" / "sign-release.sh"),
            "--dist-dir",
            str(output_dir),
            "--signer",
            "minisign",
            "--key",
            "minisign.key",
            "--dry-run",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "minisign -S" in result.stdout


def test_sign_release_dry_run_shows_keyless_cosign_bundle_commands(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.22.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )

    result = subprocess.run(
        [
            "bash",
            str(REPO / "scripts" / "sign-release.sh"),
            "--dist-dir",
            str(output_dir),
            "--signer",
            "cosign",
            "--dry-run",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "Signer: cosign keyless" in result.stdout
    assert "cosign sign-blob --yes --bundle" in result.stdout
    assert "aikeeper-v0.22.0.tar.gz.sigstore.json" in result.stdout
    assert "CHECKSUMS.txt.sigstore.json" in result.stdout
    assert "release-manifest.json.sigstore.json" in result.stdout


def test_macos_dmg_wrapper_is_thin_and_documented() -> None:
    wrapper = REPO / "packaging" / "macos" / "dmg" / "Aikeeper Installer.command"
    readme = REPO / "packaging" / "macos" / "dmg" / "README.md"

    wrapper_text = wrapper.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")

    assert "scripts/install.sh" in wrapper_text
    assert "aikeeper install all" not in wrapper_text
    assert "thin wrapper" in readme_text
    assert "does not bundle local AI Keeper data" in readme_text


def test_windows_service_prep_is_documented_with_dry_run_script() -> None:
    readme = REPO / "packaging" / "windows" / "README.md"
    script = REPO / "packaging" / "windows" / "install-service.ps1"

    readme_text = readme.read_text(encoding="utf-8")
    script_text = script.read_text(encoding="utf-8")

    assert "Windows Service Prep" in readme_text
    assert "Codex on Windows" in readme_text
    assert "metadata-only" in readme_text
    assert "`.venv` runtime" in readme_text
    assert "param(" in script_text
    assert "$DryRun" in script_text
    assert ".venv\\Scripts\\aikeeper.exe" in script_text
    assert "uv run" not in script_text

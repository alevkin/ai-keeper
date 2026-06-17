import json
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def test_public_release_hygiene_documents_are_present_and_metadata_first() -> None:
    required_docs = {
        "LICENSE": ["MIT License", "Andrei Levkin"],
        "SECURITY.md": ["Supported Versions", "metadata-only", "private disclosure"],
        "CONTRIBUTING.md": ["metadata-only", "tests", "distribution audit"],
        "PRIVACY.md": ["does not store prompts", "transcript contents", "local-only"],
        "docs/public-release-checklist.md": ["Public Release Checklist", "default branch", "license"],
    }

    for rel_path, expected_fragments in required_docs.items():
        text = (REPO / rel_path).read_text(encoding="utf-8")
        for fragment in expected_fragments:
            assert fragment in text


def test_packaging_manifest_tracks_distribution_prep_wave_targets() -> None:
    manifest = json.loads((REPO / "packaging" / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["version"] == "0.21.0"
    assert manifest["scripts"]["sign"] == "scripts/sign-release.sh"
    assert manifest["targets"]["checksums"] == "dist/CHECKSUMS.txt"
    assert manifest["targets"]["homebrew_tap_formula"] == "dist/homebrew-tap/Formula/aikeeper.rb"
    assert manifest["targets"]["ci_workflow"] == ".github/workflows/ci.yml"
    assert manifest["targets"]["release_notes"] == "dist/release-notes.md"
    assert manifest["targets"]["repo_settings_checklist"] == "docs/repo-settings-checklist.md"
    assert manifest["targets"]["macos_dmg_wrapper"] == "packaging/macos/dmg/Aikeeper Installer.command"
    assert manifest["future_targets"] == [
        "repo-owner-actions",
        "ci-follow-up",
        "release-upload-design",
        "public-launch-copy",
    ]


def test_package_script_writes_tap_formula_and_checksum_index(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.21.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    archive = output_dir / "aikeeper-v0.21.0.tar.gz"
    checksums = output_dir / "CHECKSUMS.txt"
    tap_formula = output_dir / "homebrew-tap" / "Formula" / "aikeeper.rb"
    manifest = json.loads((output_dir / "release-manifest.json").read_text(encoding="utf-8"))

    assert archive.exists()
    assert checksums.exists()
    assert f"  {archive.name}" in checksums.read_text(encoding="utf-8")
    assert tap_formula.exists()
    assert 'homepage "https://github.com/alevkin/ai-keeper"' in tap_formula.read_text(encoding="utf-8")
    assert manifest["checksums"] == checksums.name
    assert manifest["homebrew_tap_formula"] == str(tap_formula)
    assert manifest["signing"]["optional"] == ["cosign", "minisign"]


def test_sign_release_script_generates_verification_materials(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"
    subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.21.0", "--output-dir", str(output_dir)],
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
    (output_dir / "aikeeper-v0.21.0.tar.gz").write_text("package", encoding="utf-8")

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
    assert "param(" in script_text
    assert "$DryRun" in script_text
    assert "aikeeper daemon start" in script_text

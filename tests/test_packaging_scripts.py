import json
import os
import tarfile
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


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
        if name != "rollback":
            assert "aikeeper install all --port 8766" in result.stdout
        if name == "upgrade":
            assert "Rollback ref:" in result.stdout
            assert "Rollback ref: v0.12.0-dirty" not in result.stdout


def test_packaging_manifest_documents_light_packaging_surface() -> None:
    manifest_path = REPO / "packaging" / "manifest.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "AI Keeper"
    assert manifest["version"] == "0.16.0"
    assert manifest["local_only"] is True
    assert manifest["metadata_only"] is True
    assert manifest["scripts"]["install"] == "scripts/install.sh"
    assert manifest["scripts"]["package"] == "scripts/package.sh"
    assert manifest["targets"]["source_archive"] == "dist/aikeeper-<version>.tar.gz"
    assert manifest["targets"]["homebrew_formula"] == "dist/homebrew/aikeeper.rb"
    assert manifest["future_targets"] == ["macos-dmg", "windows"]


def test_package_script_builds_release_archive_manifest_and_formula(tmp_path: Path) -> None:
    output_dir = tmp_path / "dist"

    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "package.sh"), "--version", "v0.16.0", "--output-dir", str(output_dir)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )

    archive = output_dir / "aikeeper-v0.16.0.tar.gz"
    checksum = output_dir / "aikeeper-v0.16.0.tar.gz.sha256"
    manifest_path = output_dir / "release-manifest.json"
    formula = output_dir / "homebrew" / "aikeeper.rb"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert result.returncode == 0, result.stderr
    assert archive.exists()
    assert checksum.exists()
    assert formula.exists()
    assert manifest["version"] == "v0.16.0"
    assert manifest["archive"] == archive.name
    assert len(manifest["sha256"]) == 64
    assert manifest["metadata_only"] is True
    formula_text = formula.read_text(encoding="utf-8")
    assert "file://" in formula_text
    assert manifest["sha256"] in formula_text
    assert "aikeeper-install" in formula_text
    assert "aikeeper-upgrade" in formula_text
    assert "aikeeper-rollback" in formula_text

    with tarfile.open(archive, "r:gz") as package:
        names = package.getnames()

    assert "aikeeper-v0.16.0/scripts/install.sh" in names
    assert "aikeeper-v0.16.0/pyproject.toml" in names
    assert not any("/.git/" in name or "/.venv/" in name for name in names)
    assert not any(name.endswith("aikeeper.sqlite") or "/sessions/" in name for name in names)

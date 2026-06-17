import json
import os
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
    assert manifest["version"] == "0.15.0"
    assert manifest["local_only"] is True
    assert manifest["metadata_only"] is True
    assert manifest["scripts"]["install"] == "scripts/install.sh"
    assert manifest["future_targets"] == ["macos-dmg", "homebrew", "windows"]

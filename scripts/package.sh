#!/usr/bin/env bash
set -euo pipefail

VERSION=""
OUTPUT_DIR="dist"
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
AI Keeper package builder

Usage: scripts/package.sh --version VERSION [--output-dir DIR]

Builds a metadata-only source release archive, checksum files, release manifest,
and Homebrew formula layouts that install from the generated archive.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  echo "--version is required" >&2
  usage >&2
  exit 2
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "Missing required command: $PYTHON_BIN" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$PYTHON_BIN" - "$REPO_ROOT" "$OUTPUT_DIR" "$VERSION" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path


repo = Path(sys.argv[1]).resolve()
output_dir = Path(sys.argv[2]).expanduser().resolve()
version = sys.argv[3]
archive_name = f"aikeeper-{version}.tar.gz"
prefix = f"aikeeper-{version}"
archive_path = output_dir / archive_name
checksum_path = output_dir / f"{archive_name}.sha256"
checksums_path = output_dir / "CHECKSUMS.txt"
manifest_path = output_dir / "release-manifest.json"
formula_dir = output_dir / "homebrew"
formula_path = formula_dir / "aikeeper.rb"
tap_formula_dir = output_dir / "homebrew-tap" / "Formula"
tap_formula_path = tap_formula_dir / "aikeeper.rb"

excluded_dirs = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "dist",
    "output",
    ".playwright-cli",
}
excluded_suffixes = {".pyc", ".pyo", ".sqlite", ".sqlite3", ".db", ".jsonl"}
excluded_names = {".DS_Store"}


def include(path: Path) -> bool:
    rel = path.relative_to(repo)
    parts = set(rel.parts)
    if parts & excluded_dirs:
        return False
    if path.name in excluded_names:
        return False
    if path.suffix in excluded_suffixes:
        return False
    if "sessions" in parts or "archived_sessions" in parts:
        return False
    return path.is_file()


def archive_filter(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    if info.name.endswith(".sh"):
        info.mode |= stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
    return info


output_dir.mkdir(parents=True, exist_ok=True)
formula_dir.mkdir(parents=True, exist_ok=True)
tap_formula_dir.mkdir(parents=True, exist_ok=True)

with tarfile.open(archive_path, "w:gz") as package:
    for path in sorted(repo.rglob("*")):
        if include(path):
            package.add(path, arcname=f"{prefix}/{path.relative_to(repo)}", filter=archive_filter)

sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
checksum_path.write_text(f"{sha256}  {archive_name}\n", encoding="utf-8")

formula_text = f'''class Aikeeper < Formula
  desc "Local-only Codex token usage daemon and dashboard"
  homepage "https://github.com/alevkin/ai-keeper"
  url "file://{archive_path}"
  sha256 "{sha256}"

  depends_on "uv"

  def install
    libexec.install Dir["*"]
    (bin/"aikeeper-install").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/install.sh" "$@"
    EOS
    (bin/"aikeeper-upgrade").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/upgrade.sh" "$@"
    EOS
    (bin/"aikeeper-rollback").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/rollback.sh" "$@"
    EOS
    (bin/"aikeeper-publish").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/publish.sh" "$@"
    EOS
    (bin/"aikeeper-sign").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/sign-release.sh" "$@"
    EOS
    (bin/"aikeeper-release").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/release.sh" "$@"
    EOS
    (bin/"aikeeper-public-release-gate").write <<~EOS
      #!/usr/bin/env bash
      exec "#{{libexec}}/scripts/public-release-gate.sh" "$@"
    EOS
    chmod 0755, bin/"aikeeper-install"
    chmod 0755, bin/"aikeeper-upgrade"
    chmod 0755, bin/"aikeeper-rollback"
    chmod 0755, bin/"aikeeper-publish"
    chmod 0755, bin/"aikeeper-sign"
    chmod 0755, bin/"aikeeper-release"
    chmod 0755, bin/"aikeeper-public-release-gate"
  end

  test do
    system bin/"aikeeper-install", "--help"
  end

  def caveats
    <<~EOS
      AI Keeper is local-only and metadata-only.
      Run: aikeeper-install --port 8766
      Dashboard: http://127.0.0.1:8766
    EOS
  end
end
'''
formula_path.write_text(formula_text, encoding="utf-8")
tap_formula_path.write_text(formula_text, encoding="utf-8")

checksum_lines = [
    f"{sha256}  {archive_name}",
    f"{hashlib.sha256(formula_path.read_bytes()).hexdigest()}  homebrew/aikeeper.rb",
    f"{hashlib.sha256(tap_formula_path.read_bytes()).hexdigest()}  homebrew-tap/Formula/aikeeper.rb",
]
checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

manifest = {
    "name": "AI Keeper",
    "version": version,
    "archive": archive_name,
    "archive_path": str(archive_path),
    "sha256": sha256,
    "sha256_path": str(checksum_path),
    "checksums": checksums_path.name,
    "homebrew_formula": str(formula_path),
    "homebrew_tap_formula": str(tap_formula_path),
    "generated_at": datetime.now(tz=UTC).isoformat(),
    "local_only": True,
    "metadata_only": True,
    "signing": {
        "default": "cosign-keyless",
        "checksums": checksums_path.name,
        "bundles": [
            f"{archive_name}.sigstore.json",
            "CHECKSUMS.txt.sigstore.json",
            "release-manifest.json.sigstore.json",
        ],
        "optional": ["minisign"],
    },
    "excluded": ["sqlite databases", "jsonl transcripts", ".git", ".venv", ".vscode", "dist", "output"],
}
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(f"Archive: {archive_path}")
print(f"SHA256:  {checksum_path}")
print(f"Checksums: {checksums_path}")
print(f"Formula: {formula_path}")
print(f"Tap formula: {tap_formula_path}")
print(f"Manifest: {manifest_path}")
PY

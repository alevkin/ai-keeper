#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path.cwd()


def normalize_version(raw: str) -> str:
    version = raw.strip()
    if version.startswith("v"):
        version = version[1:]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"Unsupported version: {raw}")
    return version


def replace_once(text: str, pattern: str, replacement: str, path: Path) -> str:
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Could not update version in {path}")
    return updated


def update_pyproject(version: str) -> None:
    path = ROOT / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, r'^version = "[^"]+"$', f'version = "{version}"', path)
    path.write_text(text, encoding="utf-8")


def update_uv_lock(version: str) -> None:
    path = ROOT / "uv.lock"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        r'(\[\[package\]\]\nname = "aikeeper"\nversion = ")[^"]+(")',
        rf"\g<1>{version}\2",
        path,
    )
    path.write_text(text, encoding="utf-8")


def update_manifest(version: str) -> None:
    path = ROOT / "packaging" / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["version"] = version
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Update AI Keeper release metadata.")
    parser.add_argument("version", help="Semver version, with or without a leading v.")
    args = parser.parse_args()
    version = normalize_version(args.version)

    update_pyproject(version)
    update_uv_lock(version)
    update_manifest(version)
    print(f"Updated release metadata to v{version}")


if __name__ == "__main__":
    main()

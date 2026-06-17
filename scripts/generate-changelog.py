#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


ROOT = Path.cwd()


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def collect_subjects(previous_tag: str | None) -> list[str]:
    rev_range = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    output = run_git("log", "--pretty=format:%s", rev_range)
    subjects = [line.strip() for line in output.splitlines() if line.strip()]
    return [subject for subject in subjects if not subject.startswith("chore(release):")]


def build_section(version: str, subjects: list[str]) -> str:
    lines = [f"## {version}", ""]
    if subjects:
        lines.extend(f"- {subject}" for subject in subjects)
    else:
        lines.append("- No user-facing changes.")
    return "\n".join(lines).rstrip() + "\n\n"


def read_existing(path: Path) -> str:
    if not path.exists():
        return "# Changelog\n"
    return path.read_text(encoding="utf-8").rstrip() + "\n"


def remove_existing_version_section(existing: str, version: str) -> str:
    pattern = rf"(?ms)^## {re.escape(version)}\n.*?(?=^## |\Z)"
    return re.sub(pattern, "", existing).strip() + "\n"


def prepend_section(existing: str, version: str, section: str) -> str:
    heading = "# Changelog"
    existing = remove_existing_version_section(existing, version)
    if existing.startswith(heading):
        rest = existing[len(heading):].lstrip()
        return f"{heading}\n\n{section}{rest}"
    return f"{heading}\n\n{section}{existing.lstrip()}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate AI Keeper changelog from git history.")
    parser.add_argument("--version", required=True, help="Release tag, for example v1.2.3.")
    parser.add_argument("--previous-tag", default="", help="Previous release tag.")
    parser.add_argument("--output", default="CHANGELOG.md", help="Changelog path.")
    parser.add_argument("--release-notes", default="", help="Optional path for the new section only.")
    args = parser.parse_args()

    previous_tag = args.previous_tag or None
    subjects = collect_subjects(previous_tag)
    section = build_section(args.version, subjects)
    output = ROOT / args.output
    output.write_text(prepend_section(read_existing(output), args.version, section), encoding="utf-8")

    if args.release_notes:
        (ROOT / args.release_notes).write_text(section, encoding="utf-8")

    print(f"Release notes: {args.output}")


if __name__ == "__main__":
    main()

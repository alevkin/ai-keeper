# AI Keeper Packaging

This directory is a lightweight packaging contract, not a full installer build.

Current supported installer surface:

- `scripts/install.sh`
- `scripts/upgrade.sh`
- `scripts/rollback.sh`

The manifest is intentionally local-only and metadata-only. Future packagers
should preserve those defaults and avoid bundling the SQLite database, Codex
transcripts, hook payloads, or daemon logs.

Planned targets:

- macOS DMG
- Homebrew tap
- Windows service/installer

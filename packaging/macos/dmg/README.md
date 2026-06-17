# macOS DMG Prototype

This directory is a research spike for a future AI Keeper DMG.

`Aikeeper Installer.command` is intentionally a thin wrapper around
`scripts/install.sh`. It does not duplicate service installation logic, and it
does not bundle local AI Keeper data.

Future DMG work should:

- package the source tree and wrapper together
- run the same preflight checks as `scripts/install.sh`
- keep SQLite databases, logs, diagnostics bundles, Codex sessions, Claude JSONL
  files, and transcripts outside the installer
- preserve the user LaunchAgent service path
- keep rollback on `scripts/rollback.sh`

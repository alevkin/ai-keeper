# Windows Service Prep

AI Keeper does not yet ship a Windows installer. This directory documents the
future Codex on Windows service path without changing the local-only and
metadata-only contract.

Current assumptions:

- The AI Keeper `.venv` runtime has already been prepared by the installer.
- The dashboard should bind to `127.0.0.1`.
- The database should stay under `%USERPROFILE%\.aikeeper` unless
  `AIKEEPER_HOME` is set.
- Codex metadata paths may differ from macOS and must be verified before a
  supported Windows release.

The draft `install-service.ps1` supports `-DryRun` and sketches a future Windows
service command. It should not be treated as a supported installer until tested
on Windows with real Codex metadata.

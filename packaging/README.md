# AI Keeper Packaging

This directory documents the supported local packaging surface.

Current supported installer scripts:

- `scripts/install.sh`
- `scripts/upgrade.sh`
- `scripts/rollback.sh`
- `scripts/package.sh`
- `scripts/publish.sh`

Build a local release:

```bash
scripts/package.sh --version v0.18.0 --output-dir dist
```

The package builder writes:

- `dist/aikeeper-v0.18.0.tar.gz`
- `dist/aikeeper-v0.18.0.tar.gz.sha256`
- `dist/release-manifest.json`
- `dist/homebrew/aikeeper.rb`

Install from the generated Homebrew formula:

```bash
brew install --formula dist/homebrew/aikeeper.rb
aikeeper-install --port 8766
```

The package contract is intentionally local-only and metadata-only. Packages
must not bundle the SQLite database, Codex transcripts, hook payloads, daemon
logs, diagnostics bundles, `.venv`, `.vscode`, `.git`, `dist`, or `output`.

Run the distribution audit before publishing:

```bash
uv run aikeeper audit distribution --json
```

The audit verifies that release files remain metadata-only and do not contain
company-specific or private adjacent-project markers.

Publish to the private GitHub repository after tests and audit pass:

```bash
scripts/publish.sh --remote git@github.com:alevkin/ai-keeper.git --ssh-key ~/.ssh/aikeeper_publish
```

Planned targets:

- macOS DMG
- Windows service/installer

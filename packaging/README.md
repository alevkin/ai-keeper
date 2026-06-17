# AI Keeper Packaging

This directory documents the supported local packaging surface.

Current supported installer scripts:

- `scripts/install.sh`
- `scripts/upgrade.sh`
- `scripts/rollback.sh`
- `scripts/package.sh`
- `scripts/publish.sh`
- `scripts/release.sh`
- `scripts/sign-release.sh`

Build a local release:

```bash
scripts/package.sh --version v0.21.0 --output-dir dist
```

The package builder writes:

- `dist/aikeeper-v0.21.0.tar.gz`
- `dist/aikeeper-v0.21.0.tar.gz.sha256`
- `dist/CHECKSUMS.txt`
- `dist/release-manifest.json`
- `dist/homebrew/aikeeper.rb`
- `dist/homebrew-tap/Formula/aikeeper.rb`

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

Generate release verification material:

```bash
scripts/sign-release.sh --dist-dir dist --signer none
```

GitHub Releases use keyless `cosign` through GitHub OIDC and include Sigstore
bundles for the archive, `CHECKSUMS.txt`, and `release-manifest.json`. Signing
keys must not be committed or packaged.

Generate the local release bundle and notes:

```bash
scripts/release.sh --version v0.21.0 --output-dir dist --signer none
```

Use `--signer cosign` only in an OIDC-capable signing environment, such as the
GitHub release workflow.

Publish to the private GitHub repository after tests and audit pass:

```bash
scripts/publish.sh --remote git@github.com:alevkin/ai-keeper.git --ssh-key ~/.ssh/aikeeper_publish
```

Planned targets:

- dedicated Homebrew tap repository
- public issue templates
- public launch copy

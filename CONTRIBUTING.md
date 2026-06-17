# Contributing

AI Keeper is a local-only, metadata-only usage tracker. Contributions must keep
that contract intact.

## Development Setup

```bash
uv run pytest -q
uv run aikeeper audit distribution --json
```

## Privacy Rules

- Do not store prompts, assistant messages, raw transcript contents, or copied
  chat text in the database.
- Prefer identifiers, offsets, timestamps, token counts, model names, cwd, and
  git metadata.
- Keep diagnostics bounded and metadata-only.
- Add or update tests for privacy-sensitive behavior.

## Testing

Use tests before implementation for behavior changes. At minimum, run the
focused tests for the touched area and `uv run pytest -q` before publishing.

## Distribution Checks

Before opening the repository or sharing a release:

```bash
uv run aikeeper audit privacy --json
uv run aikeeper audit distribution --json
bash scripts/package.sh --version vX.Y.Z --output-dir dist
bash scripts/sign-release.sh --dist-dir dist --signer none
```

The distribution audit helps catch local project paths, company markers, and
private key references before release.

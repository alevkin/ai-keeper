# Release Upload Design

AI Keeper uses an explicit GitHub Actions release workflow on `main`.

## Automated Path

`.github/workflows/release.yml` runs after pushes to `main`, except release
commits that start with `chore(release):`.

The workflow:

- Fetches full git history and tags.
- Computes the next semver tag from Conventional Commit subjects and bodies.
- Updates `pyproject.toml`, `uv.lock`, and `packaging/manifest.json`.
- Regenerates `CHANGELOG.md` from commits since the previous tag.
- Runs tests and metadata-only audits.
- Commits the release metadata and changelog.
- Creates an annotated `v*` tag.
- Installs `cosign` with `sigstore/cosign-installer`.
- Builds release artifacts with `scripts/release.sh --signer cosign`.
- Creates a GitHub Release with the generated release notes, artifacts,
  checksums, and Sigstore bundles.

No external repository secrets are required for the default flow. The workflow
uses `GITHUB_TOKEN` through `gh release create` and GitHub OIDC for keyless
`cosign` signing.

## Local Fallback

Build and verify locally when testing a release candidate before pushing to
`main`:

   ```bash
   scripts/release.sh --version v0.22.0 --output-dir dist --signer none
   ```

Review generated files:

- `dist/aikeeper-v0.22.0.tar.gz`
- `dist/aikeeper-v0.22.0.tar.gz.sha256`
- `dist/CHECKSUMS.txt`
- `dist/SIGNING.md`
- `dist/release-manifest.json`
- `dist/homebrew-tap/Formula/aikeeper.rb`

Prepare the dedicated tap checkout locally:

   ```bash
   scripts/publish-homebrew-tap.sh \
     --version v0.24.0 \
     --dist-dir dist \
     --tap-dir output/homebrew-ai-keeper \
     --no-push
   ```

## Deferred Decisions

- When to publish `alevkin/homebrew-ai-keeper` publicly.
- When to run the first `brew install alevkin/ai-keeper/aikeeper` smoke test.
- Whether `minisign` is useful as a manual secondary signature.

PyPI publishing is deferred because the MVP is a local daemon plus OS service
installer rather than a Python library API.

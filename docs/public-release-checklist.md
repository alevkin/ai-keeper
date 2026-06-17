# Public Release Checklist

Use this checklist before changing the repository from private to public.

- Confirm the default branch is `main`.
- Confirm all commits and tags use `Andrei Levkin <alevkin@gmail.com>`.
- Confirm the license choice is intentional.
- Run `uv run pytest -q`.
- Run `uv run aikeeper audit privacy --json`.
- Run `uv run aikeeper audit distribution --json`.
- Build a package with `scripts/package.sh --version <tag> --output-dir dist`.
- Generate checksums with `scripts/sign-release.sh --dist-dir dist --signer none`.
- Run `scripts/public-release-gate.sh --version <tag> --output-dir dist --online`.
- Confirm the GitHub Release includes keyless `cosign` Sigstore bundles for the
  archive, `CHECKSUMS.txt`, and `release-manifest.json`.
- Run `scripts/publish-homebrew-tap.sh --version <tag> --dist-dir dist --tap-dir output/homebrew-tap --no-push`.
- Verify the archive excludes `.git`, `.venv`, `.vscode`, local databases,
  JSONL transcripts, logs, diagnostics bundles, and session directories.
- Review `README.md`, `SECURITY.md`, `PRIVACY.md`, and `CONTRIBUTING.md`.
- Review `.github/ISSUE_TEMPLATE/` and confirm public issues stay
  metadata-only.
- Review `docs/repo-settings-checklist.md`.
- Review `docs/github-ops-status.md`.
- Review `docs/release-upload-design.md`.
- Review `docs/public-release-gate.md`.
- Review `CHANGELOG.md`.
- Confirm no private SSH key path, company marker, or adjacent project name is
  present in tracked files.

The repository can stay private until these checks are complete.

# Public Release Gate

The public release gate is a final read-only readiness check before changing AI
Keeper from private to public.

Run it locally after a release exists:

```bash
scripts/public-release-gate.sh --version v0.22.0 --output-dir dist --online
```

Or run the manual GitHub Actions workflow:

```bash
gh workflow run "Public Release Gate" --repo alevkin/ai-keeper -f version=v0.22.0
```

The gate verifies:

- privacy audit status
- distribution audit status
- clean git worktree
- clean git author history using locally configured private marker rules
- latest release tag and metadata versions
- `CHANGELOG.md` contains the release section
- CI, release, and public gate workflows are present
- release artifacts, checksums, and manifest are valid
- release workflow is configured for keyless `cosign`
- online GitHub Release includes Sigstore bundle assets
- online GitHub repository, release, and CI state when `--online` is used

It does not change repository visibility, publish a tap repository, or write
release signing secrets.

Private marker rules are loaded from `AIKEEPER_PRIVATE_MARKERS` or
`$AIKEEPER_HOME/private-markers.toml`. See `docs/private-markers.md`.

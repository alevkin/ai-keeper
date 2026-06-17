# Release Verification

AI Keeper release artifacts are local-only and metadata-only. Verify checksums
before installing from a downloaded or copied package.

## Checksum Verification

From the release directory:

```bash
shasum -a 256 -c CHECKSUMS.txt
```

The package builder also writes a per-archive `.sha256` file for compatibility
with simple local workflows.

## Sigstore Signatures

GitHub Releases are signed by the release workflow with keyless `cosign`. The
workflow uses GitHub OIDC, so AI Keeper does not need repository signing
secrets. Signed releases include these bundle files:

- `aikeeper-<tag>.tar.gz.sigstore.json`
- `CHECKSUMS.txt.sigstore.json`
- `release-manifest.json.sigstore.json`

Verify the bundles from the release directory:

```bash
for artifact in aikeeper-*.tar.gz CHECKSUMS.txt release-manifest.json; do
  cosign verify-blob "$artifact" \
    --bundle "$artifact.sigstore.json" \
    --certificate-identity "https://github.com/alevkin/ai-keeper/.github/workflows/release.yml@refs/heads/main" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
done
```

For local packaging, `scripts/sign-release.sh` can still create checksum
material without signatures:

Examples:

```bash
bash scripts/sign-release.sh --dist-dir dist --signer none
bash scripts/sign-release.sh --dist-dir dist --signer cosign
```

`--signer cosign` expects an OIDC-capable environment such as GitHub Actions, or
a local cosign setup that can complete keyless signing. `minisign` remains a
manual fallback with an external key; do not store signing keys in this
repository.

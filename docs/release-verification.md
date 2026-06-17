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

## Optional Signatures

`scripts/sign-release.sh` can create checksum material without signatures, or
show optional `cosign` and `minisign` signing commands when the tools and keys
are available.

Examples:

```bash
bash scripts/sign-release.sh --dist-dir dist --signer none
bash scripts/sign-release.sh --dist-dir dist --signer minisign --key minisign.key
bash scripts/sign-release.sh --dist-dir dist --signer cosign --key cosign.key
```

Do not store signing keys in this repository.

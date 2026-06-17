#!/usr/bin/env bash
set -euo pipefail

DIST_DIR="dist"
SIGNER="auto"
KEY=""
DRY_RUN=0

usage() {
  cat <<'EOF'
AI Keeper release verification

Usage: scripts/sign-release.sh [--dist-dir DIR] [--signer auto|none|minisign|cosign]
                               [--key PATH] [--dry-run]

Writes CHECKSUMS.txt and SIGNING.md for release artifacts. Optional signatures
sign CHECKSUMS.txt with minisign or cosign when an external key is provided.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dist-dir)
      DIST_DIR="$2"
      shift 2
      ;;
    --signer)
      SIGNER="$2"
      shift 2
      ;;
    --key)
      KEY="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

DIST_DIR="$(cd "$DIST_DIR" && pwd)"
CHECKSUMS="$DIST_DIR/CHECKSUMS.txt"
SIGNING_DOC="$DIST_DIR/SIGNING.md"

echo "AI Keeper release verification"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

case "$SIGNER" in
  auto|none|minisign|cosign) ;;
  *)
    echo "Unsupported signer: $SIGNER" >&2
    exit 2
    ;;
esac

if [[ "$SIGNER" == "auto" ]]; then
  if [[ -n "${AIKEEPER_MINISIGN_KEY:-}" && -x "$(command -v minisign || true)" ]]; then
    SIGNER="minisign"
    KEY="${KEY:-$AIKEEPER_MINISIGN_KEY}"
  elif [[ -n "${AIKEEPER_COSIGN_KEY:-}" && -x "$(command -v cosign || true)" ]]; then
    SIGNER="cosign"
    KEY="${KEY:-$AIKEEPER_COSIGN_KEY}"
  else
    SIGNER="none"
  fi
fi

echo "+ write $CHECKSUMS"
if [[ "$DRY_RUN" -eq 0 ]]; then
  (
    cd "$DIST_DIR"
    find . -type f \
      ! -name 'CHECKSUMS.txt' \
      ! -name 'SIGNING.md' \
      ! -name '*.minisig' \
      ! -name '*.sig' \
      -print0 |
      sort -z |
      xargs -0 shasum -a 256 |
      sed 's#  \\./#  #'
  ) > "$CHECKSUMS"
fi

echo "+ write $SIGNING_DOC"
if [[ "$DRY_RUN" -eq 0 ]]; then
  cat > "$SIGNING_DOC" <<'EOF'
# AI Keeper Release Verification

Verify release checksums from this directory:

```bash
shasum -a 256 -c CHECKSUMS.txt
```

Optional signature files, when present, sign `CHECKSUMS.txt`. Signing keys are
not stored in AI Keeper packages.
EOF
fi

case "$SIGNER" in
  none)
    echo "Signer: none"
    ;;
  minisign)
    KEY="${KEY:-${AIKEEPER_MINISIGN_KEY:-}}"
    if [[ -z "$KEY" ]]; then
      echo "minisign signer requires --key or AIKEEPER_MINISIGN_KEY" >&2
      exit 2
    fi
    echo "+ minisign -S -s $KEY -m $CHECKSUMS"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      command -v minisign >/dev/null 2>&1 || { echo "Missing minisign" >&2; exit 1; }
      minisign -S -s "$KEY" -m "$CHECKSUMS"
    fi
    ;;
  cosign)
    KEY="${KEY:-${AIKEEPER_COSIGN_KEY:-}}"
    if [[ -z "$KEY" ]]; then
      echo "cosign signer requires --key or AIKEEPER_COSIGN_KEY" >&2
      exit 2
    fi
    echo "+ cosign sign-blob --key $KEY --output-signature $CHECKSUMS.sig $CHECKSUMS"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      command -v cosign >/dev/null 2>&1 || { echo "Missing cosign" >&2; exit 1; }
      cosign sign-blob --key "$KEY" --output-signature "$CHECKSUMS.sig" "$CHECKSUMS"
    fi
    ;;
esac

echo "Verification: shasum -a 256 -c CHECKSUMS.txt"

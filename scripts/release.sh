#!/usr/bin/env bash
set -euo pipefail

VERSION=""
OUTPUT_DIR="dist"
SIGNER="none"
SKIP_TESTS=0
DRY_RUN=0

usage() {
  cat <<'EOF'
AI Keeper release

Usage: scripts/release.sh --version VERSION [--output-dir DIR]
                          [--signer none|auto|minisign|cosign]
                          [--skip-tests] [--dry-run]

Runs local release checks, builds package artifacts, writes release notes, and
generates checksum/signing materials. This script does not upload GitHub
releases and does not use repository secrets.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --signer)
      SIGNER="$2"
      shift 2
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
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

if [[ -z "$VERSION" ]]; then
  echo "--version is required" >&2
  usage >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$(cd "$(dirname "$OUTPUT_DIR")" && pwd)/$(basename "$OUTPUT_DIR")"
RELEASE_NOTES="$OUTPUT_DIR/release-notes.md"

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

write_release_notes() {
  echo "+ write $RELEASE_NOTES"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return
  fi
  mkdir -p "$OUTPUT_DIR"
  local previous_tag
  previous_tag="$(git -C "$REPO_ROOT" tag --list 'v*' --sort=-v:refname | head -n 1 || true)"
  {
    printf '# AI Keeper %s\n\n' "$VERSION"
    printf 'Local-only, metadata-only release artifacts.\n\n'
    printf '## Verification\n\n'
    printf '```bash\nshasum -a 256 -c CHECKSUMS.txt\n```\n\n'
    printf '## Changes\n\n'
    if [[ -n "$previous_tag" ]]; then
      git -C "$REPO_ROOT" log --oneline "${previous_tag}..HEAD"
    else
      git -C "$REPO_ROOT" log --oneline
    fi
  } > "$RELEASE_NOTES"
}

echo "AI Keeper release"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  run uv run pytest -q
fi
run uv run aikeeper audit privacy --json
run uv run aikeeper audit distribution --json
run bash scripts/package.sh --version "$VERSION" --output-dir "$OUTPUT_DIR"
write_release_notes
run bash scripts/sign-release.sh --dist-dir "$OUTPUT_DIR" --signer "$SIGNER"

echo "Release notes: $RELEASE_NOTES"

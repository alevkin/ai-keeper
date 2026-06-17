#!/usr/bin/env bash
set -euo pipefail

VERSION=""
OUTPUT_DIR="dist"
ONLINE=0
SKIP_TESTS=0
ALLOW_DIRTY=0
PYTHON_BIN="${PYTHON:-python3}"

usage() {
  cat <<'EOF'
AI Keeper public release gate

Usage: scripts/public-release-gate.sh --version VERSION [--output-dir DIR]
                                      [--online] [--skip-tests] [--allow-dirty]

Builds local release artifacts, verifies checksums and formulas, then runs the
metadata-only public-release gate. Use --online after GitHub authentication to
check the private repository, GitHub Release, and recent CI state too.
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
    --online)
      ONLINE=1
      shift
      ;;
    --skip-tests)
      SKIP_TESTS=1
      shift
      ;;
    --allow-dirty)
      ALLOW_DIRTY=1
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
GATE_DB="$(mktemp "${TMPDIR:-/tmp}/aikeeper-gate.XXXXXX.sqlite")"
trap 'rm -f "$GATE_DB"' EXIT

echo "AI Keeper public release gate"
echo "Version: $VERSION"
echo "Output: $OUTPUT_DIR"

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  uv --directory "$REPO_ROOT" run pytest -q
fi

bash "$REPO_ROOT/scripts/package.sh" --version "$VERSION" --output-dir "$OUTPUT_DIR"
bash "$REPO_ROOT/scripts/sign-release.sh" --dist-dir "$OUTPUT_DIR" --signer none
(cd "$OUTPUT_DIR" && shasum -a 256 -c CHECKSUMS.txt)
ruby -c "$OUTPUT_DIR/homebrew/aikeeper.rb"
ruby -c "$OUTPUT_DIR/homebrew-tap/Formula/aikeeper.rb"

args=(
  uv --directory "$REPO_ROOT" run aikeeper audit public-release
  --repo-root "$REPO_ROOT"
  --db-path "$GATE_DB"
  --dist-dir "$OUTPUT_DIR"
  --tag "$VERSION"
  --json
)
if [[ "$ONLINE" -eq 1 ]]; then
  args+=(--online)
fi
if [[ "$ALLOW_DIRTY" -eq 1 ]]; then
  args+=(--allow-dirty)
fi

"${args[@]}"

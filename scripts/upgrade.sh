#!/usr/bin/env bash
set -euo pipefail

PORT=8766
DRY_RUN=0
TARGET=""
NO_FETCH=0

usage() {
  cat <<'EOF'
AI Keeper upgrade

Usage: scripts/upgrade.sh [--port PORT] [--target REF] [--no-fetch] [--dry-run]

Records the current version for rollback, optionally fetches tags, checks out
the requested ref, then reruns the local installer.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="$2"
      shift 2
      ;;
    --target)
      TARGET="$2"
      shift 2
      ;;
    --no-fetch)
      NO_FETCH=1
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
AIKEEPER_HOME="${AIKEEPER_HOME:-$HOME/.aikeeper}"
ROLLBACK_FILE="$AIKEEPER_HOME/rollback-ref"

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

echo "AI Keeper upgrade"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

require_cmd git
require_cmd uv
mkdir -p "$AIKEEPER_HOME"

CURRENT_VERSION="$(git -C "$REPO_ROOT" describe --tags --always --dirty)"
CURRENT_REF="$(git -C "$REPO_ROOT" rev-parse --verify HEAD)"
echo "Current version: $CURRENT_VERSION"
echo "Rollback ref: $CURRENT_REF"
echo "Rollback file: $ROLLBACK_FILE"
if [[ "$DRY_RUN" -eq 0 ]]; then
  printf '%s\n' "$CURRENT_REF" > "$ROLLBACK_FILE"
fi

if [[ "$NO_FETCH" -eq 0 ]]; then
  run git -C "$REPO_ROOT" fetch --tags --prune
fi

if [[ -n "$TARGET" ]]; then
  run git -C "$REPO_ROOT" checkout "$TARGET"
fi

run uv --directory "$REPO_ROOT" run aikeeper install all --port "$PORT"
run uv --directory "$REPO_ROOT" run aikeeper doctor --port "$PORT"

echo "AI Keeper upgrade complete"

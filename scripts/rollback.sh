#!/usr/bin/env bash
set -euo pipefail

PORT=8766
DRY_RUN=0
TARGET="${AIKEEPER_TEST_ROLLBACK_TARGET:-}"

usage() {
  cat <<'EOF'
AI Keeper rollback

Usage: scripts/rollback.sh [--port PORT] [--target REF] [--dry-run]

Rolls the working copy back to a known ref and reruns the local installer.
If --target is omitted, the script reads $AIKEEPER_HOME/rollback-ref.
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
AIKEEPER_BIN="$REPO_ROOT/.venv/bin/aikeeper"
if [[ "$(uname -s)" == MINGW* || "$(uname -s)" == CYGWIN* ]]; then
  AIKEEPER_BIN="$REPO_ROOT/.venv/Scripts/aikeeper.exe"
fi

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

ensure_runtime() {
  if [[ -x "$AIKEEPER_BIN" ]]; then
    echo "aikeeper: ok ($AIKEEPER_BIN)"
    return
  fi
  require_cmd uv
  echo "+ bootstrap AI Keeper runtime"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    uv --directory "$REPO_ROOT" sync --frozen --no-dev
  fi
}

echo "AI Keeper rollback"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

require_cmd git
ensure_runtime

if [[ -z "$TARGET" && -f "$ROLLBACK_FILE" ]]; then
  TARGET="$(head -n 1 "$ROLLBACK_FILE")"
fi

if [[ -z "$TARGET" ]]; then
  echo "No rollback target. Pass --target REF or create $ROLLBACK_FILE." >&2
  exit 1
fi

echo "Rollback target: $TARGET"
run git -C "$REPO_ROOT" checkout "$TARGET"
run "$AIKEEPER_BIN" install all --port "$PORT"
run "$AIKEEPER_BIN" doctor --port "$PORT"

echo "AI Keeper rollback complete"

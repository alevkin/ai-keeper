#!/usr/bin/env bash
set -euo pipefail

PORT=8766
DRY_RUN=0

usage() {
  cat <<'EOF'
AI Keeper installer

Usage: scripts/install.sh [--port PORT] [--dry-run]

Installs the local SQLite schema, Codex hooks, and macOS LaunchAgent.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)
      PORT="$2"
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

preflight_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "$1: ok ($(command -v "$1"))"
  else
    echo "$1: missing"
    exit 1
  fi
}

open_dashboard() {
  local url="$1"
  echo "AI Keeper dashboard: $url"
  if [[ "${AIKEEPER_NO_OPEN:-}" == "1" ]]; then
    return
  fi
  if [[ "$PLATFORM" == "Darwin" ]]; then
    echo "+ open $url"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      open "$url" >/dev/null 2>&1 || echo "Warning: could not open dashboard URL: $url" >&2
    fi
  elif command -v xdg-open >/dev/null 2>&1; then
    echo "+ xdg-open $url"
    if [[ "$DRY_RUN" -eq 0 ]]; then
      xdg-open "$url" >/dev/null 2>&1 || echo "Warning: could not open dashboard URL: $url" >&2
    fi
  fi
}

echo "AI Keeper install"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

PLATFORM="$(uname -s)"
echo "Preflight"
echo "Platform: $PLATFORM"
preflight_cmd uv
if [[ "$PLATFORM" == "Darwin" ]]; then
  preflight_cmd launchctl
else
  echo "launchctl: skipped"
fi

run uv --directory "$REPO_ROOT" run aikeeper install all --port "$PORT"
run uv --directory "$REPO_ROOT" run aikeeper doctor --port "$PORT"

open_dashboard "http://127.0.0.1:$PORT"

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

preflight_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "$1: ok ($(command -v "$1"))"
  else
    echo "$1: missing"
    exit 1
  fi
}

ensure_runtime() {
  if [[ -x "$AIKEEPER_BIN" ]]; then
    echo "aikeeper: ok ($AIKEEPER_BIN)"
    return
  fi
  preflight_cmd uv
  echo "+ bootstrap AI Keeper runtime"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    uv --directory "$REPO_ROOT" sync --frozen --no-dev
  fi
}

open_dashboard() {
  local url="$1"
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

wait_for_dashboard() {
  local url="$1"
  local ping_url="$url/api/ping"
  local attempts="${AIKEEPER_DASHBOARD_WAIT_ATTEMPTS:-60}"
  local delay="${AIKEEPER_DASHBOARD_WAIT_DELAY:-0.5}"
  echo "Waiting for AI Keeper dashboard: $ping_url"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return 0
  fi
  for ((i = 1; i <= attempts; i++)); do
    if curl --fail --silent --show-error "$ping_url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

echo "AI Keeper install"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

PLATFORM="$(uname -s)"
echo "Preflight"
echo "Platform: $PLATFORM"
ensure_runtime
preflight_cmd curl
if [[ "$PLATFORM" == "Darwin" ]]; then
  preflight_cmd launchctl
else
  echo "launchctl: skipped"
fi

run "$AIKEEPER_BIN" install all --port "$PORT"

dashboard_url="http://127.0.0.1:$PORT"
echo "AI Keeper dashboard: $dashboard_url"
if wait_for_dashboard "$dashboard_url"; then
  run "$AIKEEPER_BIN" doctor --port "$PORT"
  open_dashboard "$dashboard_url"
else
  run "$AIKEEPER_BIN" doctor --port "$PORT"
  echo "Warning: dashboard did not become ready; browser was not opened." >&2
fi

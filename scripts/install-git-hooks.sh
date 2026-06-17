#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=""
HOOKS_DIR=""

usage() {
  cat <<'EOF'
AI Keeper local git hook installer

Usage: scripts/install-git-hooks.sh [--repo-root PATH] [--hooks-dir PATH]

Installs local pre-commit and pre-push hooks that run metadata-only AI Keeper
distribution checks. Private marker values are read from
$AIKEEPER_PRIVATE_MARKERS or $AIKEEPER_HOME/private-markers.toml, never from the
repository.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="$2"
      shift 2
      ;;
    --hooks-dir)
      HOOKS_DIR="$2"
      shift 2
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
if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  REPO_ROOT="$(cd "$REPO_ROOT" && pwd)"
fi
if [[ -z "$HOOKS_DIR" ]]; then
  HOOKS_DIR="$REPO_ROOT/.git/hooks"
fi
mkdir -p "$HOOKS_DIR"

write_hook() {
  local path="$1"
  local body="$2"
  if [[ -f "$path" && ! -f "$path.aikeeper.bak" ]]; then
    cp "$path" "$path.aikeeper.bak"
  fi
  printf '%s\n' "$body" >"$path"
  chmod 0755 "$path"
}

read -r -d '' PRE_COMMIT <<EOF || true
#!/usr/bin/env bash
set -euo pipefail
cd "$REPO_ROOT"
# Private markers are read from AIKEEPER_PRIVATE_MARKERS or AIKEEPER_HOME.
echo "AI Keeper: distribution audit"
uv run --no-sync aikeeper audit distribution --json >/dev/null
EOF

read -r -d '' PRE_PUSH <<EOF || true
#!/usr/bin/env bash
set -euo pipefail
cd "$REPO_ROOT"
# Private markers are read from AIKEEPER_PRIVATE_MARKERS or AIKEEPER_HOME.
echo "AI Keeper: distribution audit"
uv run --no-sync aikeeper audit distribution --json >/dev/null
echo "AI Keeper: author history private marker audit"
uv run --no-sync python - <<'PY'
from __future__ import annotations

import subprocess
import sys

from aikeeper.private_markers import load_private_marker_rules

result = subprocess.run(
    ["git", "log", "--format=%an <%ae>"],
    capture_output=True,
    text=True,
    check=False,
)
if result.returncode != 0:
    print(result.stderr or result.stdout or "git log failed", file=sys.stderr)
    raise SystemExit(result.returncode)

matched_rule_ids = [rule.rule_id for rule in load_private_marker_rules() if rule.pattern.search(result.stdout)]
if matched_rule_ids:
    print(
        "AI Keeper: private marker rule(s) matched git author history: "
        + ", ".join(matched_rule_ids),
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
EOF

write_hook "$HOOKS_DIR/pre-commit" "$PRE_COMMIT"
write_hook "$HOOKS_DIR/pre-push" "$PRE_PUSH"

echo "Installed AI Keeper git hooks in $HOOKS_DIR"

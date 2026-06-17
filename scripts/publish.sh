#!/usr/bin/env bash
set -euo pipefail

REMOTE="${AIKEEPER_GITHUB_REMOTE:-git@github.com:alevkin/ai-keeper.git}"
SSH_KEY="${AIKEEPER_GITHUB_SSH_KEY:-}"
BRANCH=""
AUTHOR_NAME="${AIKEEPER_GIT_AUTHOR_NAME:-Andrei Levkin}"
AUTHOR_EMAIL="${AIKEEPER_GIT_AUTHOR_EMAIL:-alevkin@gmail.com}"
DRY_RUN=0
SKIP_AUDIT=0

usage() {
  cat <<'EOF'
AI Keeper publish

Usage: scripts/publish.sh [--remote URL] --ssh-key PATH [--branch BRANCH]
                          [--author-name NAME] [--author-email EMAIL]
                          [--skip-audit] [--dry-run]

Configures the local git author and origin remote, runs the distribution audit,
then pushes the current HEAD and tags to a private GitHub repository using the
provided SSH key only for the push commands.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --remote)
      REMOTE="$2"
      shift 2
      ;;
    --ssh-key)
      SSH_KEY="$2"
      shift 2
      ;;
    --branch)
      BRANCH="$2"
      shift 2
      ;;
    --author-name)
      AUTHOR_NAME="$2"
      shift 2
      ;;
    --author-email)
      AUTHOR_EMAIL="$2"
      shift 2
      ;;
    --skip-audit)
      SKIP_AUDIT=1
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

run() {
  echo "+ $*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    "$@"
  fi
}

run_git_push() {
  local ssh_command="ssh -i $SSH_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
  echo "+ GIT_SSH_COMMAND=$ssh_command git push $*"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    GIT_SSH_COMMAND="$ssh_command" git -C "$REPO_ROOT" push "$@"
  fi
}

run_distribution_audit() {
  echo "+ uv --directory $REPO_ROOT run aikeeper audit distribution --json"
  if [[ "$DRY_RUN" -eq 0 ]]; then
    local audit_json
    audit_json="$(uv --directory "$REPO_ROOT" run aikeeper audit distribution --json)"
    printf '%s\n' "$audit_json"
    printf '%s\n' "$audit_json" | python3 -c 'import json, sys; sys.exit(0 if json.load(sys.stdin).get("status") == "pass" else 1)' || {
      echo "Distribution audit failed; refusing to publish." >&2
      exit 1
    }
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

echo "AI Keeper publish"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi

require_cmd git
require_cmd uv
if [[ "$DRY_RUN" -eq 0 && "$SKIP_AUDIT" -eq 0 ]]; then
  require_cmd python3
fi

if [[ -z "$SSH_KEY" ]]; then
  echo "--ssh-key is required" >&2
  exit 2
fi

if [[ "$DRY_RUN" -eq 0 && ! -f "$SSH_KEY" ]]; then
  echo "SSH key does not exist: $SSH_KEY" >&2
  exit 1
fi

if [[ -z "$BRANCH" ]]; then
  BRANCH="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
fi

REF="${AIKEEPER_PUBLISH_TEST_REF:-$(git -C "$REPO_ROOT" describe --tags --always --dirty)}"

echo "Repository: $REMOTE"
echo "Branch: $BRANCH"
echo "Ref: $REF"
echo "Author: $AUTHOR_NAME <$AUTHOR_EMAIL>"

run git -C "$REPO_ROOT" config user.name "$AUTHOR_NAME"
run git -C "$REPO_ROOT" config user.email "$AUTHOR_EMAIL"

if [[ "$SKIP_AUDIT" -eq 0 ]]; then
  run_distribution_audit
fi

if git -C "$REPO_ROOT" remote get-url origin >/dev/null 2>&1; then
  CURRENT_REMOTE="$(git -C "$REPO_ROOT" remote get-url origin)"
  if [[ "$CURRENT_REMOTE" != "$REMOTE" ]]; then
    run git -C "$REPO_ROOT" remote set-url origin "$REMOTE"
  fi
else
  run git -C "$REPO_ROOT" remote add origin "$REMOTE"
fi

run_git_push origin "HEAD:refs/heads/$BRANCH"
run_git_push origin --tags

echo "AI Keeper publish complete"

#!/usr/bin/env bash
set -euo pipefail

VERSION=""
DIST_DIR="dist"
TAP_DIR=""
TAP_REPO="${AIKEEPER_HOMEBREW_TAP_REPO:-alevkin/homebrew-tap}"
REMOTE="${AIKEEPER_HOMEBREW_TAP_REMOTE:-git@github.com:alevkin/homebrew-tap.git}"
SSH_KEY="${AIKEEPER_GITHUB_SSH_KEY:-}"
AUTHOR_NAME="${AIKEEPER_GIT_AUTHOR_NAME:-Andrei Levkin}"
AUTHOR_EMAIL="${AIKEEPER_GIT_AUTHOR_EMAIL:-alevkin@gmail.com}"
NO_PUSH=0
DRY_RUN=0
SKIP_BUILD=0

usage() {
  cat <<'EOF'
AI Keeper Homebrew tap publisher

Usage: scripts/publish-homebrew-tap.sh --version VERSION [--dist-dir DIR]
                                       [--tap-dir DIR] [--tap-repo OWNER/REPO]
                                       [--remote URL] [--ssh-key PATH]
                                       [--no-push] [--skip-build] [--dry-run]

Scaffolds a dedicated Homebrew tap checkout with Formula/aikeeper.rb and a
README. By default it can push the tap repository with the provided SSH key.
Use --no-push to prepare or test the tap locally without network writes.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)
      VERSION="$2"
      shift 2
      ;;
    --dist-dir)
      DIST_DIR="$2"
      shift 2
      ;;
    --tap-dir)
      TAP_DIR="$2"
      shift 2
      ;;
    --tap-repo)
      TAP_REPO="$2"
      shift 2
      ;;
    --remote)
      REMOTE="$2"
      shift 2
      ;;
    --ssh-key)
      SSH_KEY="$2"
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
    --no-push)
      NO_PUSH=1
      shift
      ;;
    --skip-build)
      SKIP_BUILD=1
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
DIST_DIR="$(cd "$(dirname "$DIST_DIR")" && pwd)/$(basename "$DIST_DIR")"
if [[ -z "$TAP_DIR" ]]; then
  TAP_DIR="$REPO_ROOT/output/homebrew-tap"
fi
tap_parent="$(dirname "$TAP_DIR")"
if [[ "$DRY_RUN" -eq 0 ]]; then
  mkdir -p "$tap_parent"
fi
if [[ -d "$tap_parent" ]]; then
  TAP_DIR="$(cd "$tap_parent" && pwd)/$(basename "$TAP_DIR")"
fi
FORMULA_SOURCE="$DIST_DIR/homebrew-tap/Formula/aikeeper.rb"

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
    GIT_SSH_COMMAND="$ssh_command" git -C "$TAP_DIR" push "$@"
  fi
}

write_readme() {
  local readme="$TAP_DIR/README.md"
  local install_ref="${TAP_REPO/homebrew-/}"
  echo "+ write $readme"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    return
  fi
  cat > "$readme" <<EOF
# AI Keeper Homebrew Tap

Dedicated Homebrew tap for AI Keeper.

Install the latest release:

\`\`\`bash
brew install $install_ref/aikeeper
\`\`\`

Or tap first:

\`\`\`bash
brew tap $install_ref
brew install aikeeper
\`\`\`

AI Keeper is local-only and metadata-only. Release artifacts are published from
https://github.com/alevkin/ai-keeper and signed with keyless cosign in the main
repository release workflow.
EOF
}

echo "AI Keeper Homebrew tap publisher"
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "DRY RUN"
fi
echo "Version: $VERSION"
echo "Tap repo: $TAP_REPO"
echo "Tap dir: $TAP_DIR"
echo "Remote: $REMOTE"

command -v git >/dev/null 2>&1 || { echo "Missing git" >&2; exit 1; }
command -v ruby >/dev/null 2>&1 || { echo "Missing ruby" >&2; exit 1; }

if [[ "$SKIP_BUILD" -eq 0 && ! -f "$FORMULA_SOURCE" ]]; then
  run bash "$REPO_ROOT/scripts/package.sh" --version "$VERSION" --output-dir "$DIST_DIR"
fi

if [[ "$DRY_RUN" -eq 0 && ! -f "$FORMULA_SOURCE" ]]; then
  echo "Missing tap formula: $FORMULA_SOURCE" >&2
  exit 1
fi

if [[ "$NO_PUSH" -eq 0 && -z "$SSH_KEY" ]]; then
  echo "--ssh-key is required unless --no-push is used" >&2
  exit 2
fi
if [[ "$NO_PUSH" -eq 0 && "$DRY_RUN" -eq 0 && ! -f "$SSH_KEY" ]]; then
  echo "SSH key does not exist: $SSH_KEY" >&2
  exit 1
fi

run mkdir -p "$TAP_DIR/Formula"
run cp "$FORMULA_SOURCE" "$TAP_DIR/Formula/aikeeper.rb"
write_readme
run ruby -c "$TAP_DIR/Formula/aikeeper.rb"

if [[ "$DRY_RUN" -eq 0 ]]; then
  if [[ ! -d "$TAP_DIR/.git" ]]; then
    git -C "$TAP_DIR" init
    git -C "$TAP_DIR" branch -M main
  fi
  git -C "$TAP_DIR" config user.name "$AUTHOR_NAME"
  git -C "$TAP_DIR" config user.email "$AUTHOR_EMAIL"
  git -C "$TAP_DIR" add Formula/aikeeper.rb README.md
  if git -C "$TAP_DIR" diff --cached --quiet; then
    echo "No tap changes to commit."
  else
    git -C "$TAP_DIR" commit -m "aikeeper $VERSION"
  fi
fi

if [[ "$NO_PUSH" -eq 1 ]]; then
  echo "Push: skipped"
else
  if git -C "$TAP_DIR" remote get-url origin >/dev/null 2>&1; then
    current_remote="$(git -C "$TAP_DIR" remote get-url origin)"
    if [[ "$current_remote" != "$REMOTE" ]]; then
      run git -C "$TAP_DIR" remote set-url origin "$REMOTE"
    fi
  else
    run git -C "$TAP_DIR" remote add origin "$REMOTE"
  fi
  run_git_push origin HEAD:refs/heads/main
  echo "Push: complete"
fi

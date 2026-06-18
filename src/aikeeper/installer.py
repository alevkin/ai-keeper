from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from pathlib import Path

from aikeeper.settings import codex_home as default_codex_home


HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")


def _project_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def _hook_command() -> str:
    root = _project_root()
    if root:
        return f"uv --directory {shlex.quote(str(root))} run aikeeper hook codex"
    return "aikeeper hook codex"


def _hook_entry() -> dict:
    return {"type": "command", "command": _hook_command(), "timeout": 30, "statusMessage": "Syncing AI Keeper"}


def _is_ai_keeper_hook(hook: dict) -> bool:
    command = str(hook.get("command") or "").strip()
    return command == _hook_command() or command.endswith("aikeeper hook codex")


def _target_path(scope: str, codex_home: Path, project_dir: Path) -> Path:
    if scope == "user":
        return codex_home / "hooks.json"
    if scope == "project":
        return project_dir / ".codex" / "hooks.json"
    raise ValueError("scope must be user or project")


def install_codex_hooks(*, scope: str = "user", codex_home: Path | None = None, project_dir: Path | None = None) -> Path:
    home = codex_home or default_codex_home()
    target = _target_path(scope, home, project_dir or Path.cwd())
    target.parent.mkdir(parents=True, exist_ok=True)

    data: dict = {"hooks": {}}
    if target.exists():
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {"hooks": {}}
    hooks = data.setdefault("hooks", {})
    for event_name in HOOK_EVENTS:
        groups = hooks.setdefault(event_name, [])
        existing = False
        for group in groups:
            for hook in group.get("hooks", []):
                if hook.get("command") == _hook_command():
                    existing = True
        if not existing:
            groups.append({"hooks": [_hook_entry()]})
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def codex_hooks_installed(*, scope: str = "user", codex_home: Path | None = None, project_dir: Path | None = None) -> bool:
    home = codex_home or default_codex_home()
    target = _target_path(scope, home, project_dir or Path.cwd())
    if not target.exists():
        return False
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    hooks = data.get("hooks", {})
    for event_name in HOOK_EVENTS:
        groups = hooks.get(event_name, [])
        if not any(_is_ai_keeper_hook(hook) for group in groups for hook in group.get("hooks", [])):
            return False
    return True


def uninstall_codex_hooks(
    *,
    scope: str = "user",
    codex_home: Path | None = None,
    project_dir: Path | None = None,
) -> Path:
    home = codex_home or default_codex_home()
    target = _target_path(scope, home, project_dir or Path.cwd())
    if not target.exists():
        return target

    backup = target.with_suffix(target.suffix + ".bak")
    shutil.copy2(target, backup)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {"hooks": {}}

    hooks = data.setdefault("hooks", {})
    for event_name in HOOK_EVENTS:
        remaining_groups = []
        for group in hooks.get(event_name, []):
            remaining_hooks = [hook for hook in group.get("hooks", []) if not _is_ai_keeper_hook(hook)]
            if remaining_hooks:
                updated_group = dict(group)
                updated_group["hooks"] = remaining_hooks
                remaining_groups.append(updated_group)
        hooks[event_name] = remaining_groups

    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def _write_executable(path: Path, body: str) -> None:
    if path.exists() and not path.with_suffix(path.suffix + ".aikeeper.bak").exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".aikeeper.bak"))
    path.write_text(body.rstrip() + "\n", encoding="utf-8")
    path.chmod(0o755)


def _workflow_pre_commit(repo_root: Path) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
cd {shlex.quote(str(repo_root))}
# Private markers are read from AIKEEPER_PRIVATE_MARKERS or AIKEEPER_HOME.
echo "AI Keeper: distribution audit"
uv run --no-sync aikeeper audit distribution --json >/dev/null
"""


def _workflow_commit_msg() -> str:
    return """#!/usr/bin/env bash
set -euo pipefail

MESSAGE_FILE="$1"
SUBJECT="$(sed -n '1p' "$MESSAGE_FILE")"

case "$SUBJECT" in
  Merge\\ *|Revert\\ *) exit 0 ;;
esac

if ! printf '%s\\n' "$SUBJECT" | grep -Eq '^(feat|fix|docs|test|refactor|perf|build|ci|chore|revert)(\\([A-Za-z0-9._/-]+\\))?!?: .+'; then
  cat >&2 <<'MSG'
AI Keeper: commit subject should follow Conventional Commits.
Examples:
  feat: add task economics dashboard
  fix(hooks): restore dashboard link detection
MSG
  exit 1
fi

BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [[ -n "$BRANCH" && ! "$BRANCH" =~ ^(main|master|develop|release/.*)$ ]]; then
  if ! printf '%s\\n' "$BRANCH" | grep -Eiq '([A-Z][A-Z0-9]+-[0-9]+|GH-[0-9]+|ISSUE-[0-9]+|PR-[0-9]+|task/|feature/|fix/|docs/|chore/)'; then
    echo "AI Keeper: branch does not expose a task key/pattern, outcome attribution may be weaker." >&2
  fi
fi
"""


def _workflow_pre_push(repo_root: Path) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
cd {shlex.quote(str(repo_root))}
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
"""


def _workflow_hooks_dir(repo_root: Path) -> Path:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--git-path", "hooks"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return repo_root / ".git" / "hooks"
    hooks_path = Path(result.stdout.strip())
    if hooks_path.is_absolute():
        return hooks_path
    return repo_root / hooks_path


def install_workflow_harness_hooks(*, repo_root: Path | None = None, hooks_dir: Path | None = None) -> Path:
    root = (repo_root or Path.cwd()).expanduser().resolve()
    target_dir = hooks_dir.expanduser() if hooks_dir else _workflow_hooks_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    _write_executable(target_dir / "pre-commit", _workflow_pre_commit(root))
    _write_executable(target_dir / "commit-msg", _workflow_commit_msg())
    _write_executable(target_dir / "pre-push", _workflow_pre_push(root))
    return target_dir

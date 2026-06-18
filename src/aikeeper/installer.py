from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from aikeeper.settings import codex_home as default_codex_home


HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop")
HOOK_STATUS_MESSAGES = {
    "SessionStart": "AI Keeper: prepare local session tracking",
    "UserPromptSubmit": "AI Keeper: attach local budget context",
    "Stop": "AI Keeper: sync local usage metadata",
}
_CODEX_HOOK_STATE_EVENTS = {
    "SessionStart": "sessionStart",
    "UserPromptSubmit": "userPromptSubmit",
    "Stop": "stop",
}


@dataclass(frozen=True)
class CodexHookTrustStatus:
    installed: bool
    ready: bool
    hooks_path: Path
    config_path: Path
    missing_events: tuple[str, ...]
    untrusted_events: tuple[str, ...]
    disabled_events: tuple[str, ...]


def _project_root() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def _homebrew_opt_aikeeper_executable(root: Path) -> Path | None:
    if (
        root.name == "libexec"
        and root.parent.parent.name == "aikeeper"
        and root.parent.parent.parent.name == "Cellar"
    ):
        prefix = root.parent.parent.parent.parent
        candidate = prefix / "opt" / "aikeeper" / "libexec" / ".venv" / "bin" / "aikeeper"
        if candidate.exists():
            return candidate
    return None


def _project_aikeeper_executable(root: Path) -> Path | None:
    homebrew_executable = _homebrew_opt_aikeeper_executable(root)
    if homebrew_executable:
        return homebrew_executable
    for relative in (Path(".venv") / "bin" / "aikeeper", Path(".venv") / "Scripts" / "aikeeper.exe"):
        candidate = root / relative
        if candidate.exists():
            return candidate
    return None


def _hook_command() -> str:
    root = _project_root()
    if root:
        executable = _project_aikeeper_executable(root)
        if executable:
            return shlex.join([str(executable), "hook", "codex"])
    return "aikeeper hook codex"


def _hook_entry(event_name: str) -> dict:
    return {
        "type": "command",
        "command": _hook_command(),
        "timeout": 30,
        "statusMessage": HOOK_STATUS_MESSAGES[event_name],
    }


def _is_ai_keeper_hook(hook: dict) -> bool:
    command = str(hook.get("command") or "").strip()
    if command == _hook_command():
        return True
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    return len(parts) >= 3 and parts[-2:] == ["hook", "codex"] and Path(parts[-3]).name == "aikeeper"


def _target_path(scope: str, codex_home: Path, project_dir: Path) -> Path:
    if scope == "user":
        return codex_home / "hooks.json"
    if scope == "project":
        return project_dir / ".codex" / "hooks.json"
    raise ValueError("scope must be user or project")


def _codex_hook_state_key(hooks_path: Path, event_name: str, group_index: int, hook_index: int) -> str:
    event_key = _CODEX_HOOK_STATE_EVENTS[event_name]
    return f"{hooks_path}:{event_key}:{group_index}:{hook_index}"


def _codex_config_path(codex_home: Path) -> Path:
    return codex_home / "config.toml"


def _read_hooks_json(target: Path) -> dict | None:
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _ai_keeper_hook_positions(data: dict) -> dict[str, tuple[int, int]]:
    positions: dict[str, tuple[int, int]] = {}
    hooks = data.get("hooks", {})
    for event_name in HOOK_EVENTS:
        for group_index, group in enumerate(hooks.get(event_name, [])):
            for hook_index, hook in enumerate(group.get("hooks", [])):
                if _is_ai_keeper_hook(hook):
                    positions[event_name] = (group_index, hook_index)
                    break
            if event_name in positions:
                break
    return positions


def _codex_hook_state(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return {}
    state = hooks.get("state", {})
    return state if isinstance(state, dict) else {}


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
        updated_groups = []
        for group in groups:
            remaining_hooks = [hook for hook in group.get("hooks", []) if not _is_ai_keeper_hook(hook)]
            if remaining_hooks:
                updated_group = dict(group)
                updated_group["hooks"] = remaining_hooks
                updated_groups.append(updated_group)
        updated_groups.append({"hooks": [_hook_entry(event_name)]})
        hooks[event_name] = updated_groups
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def codex_hooks_installed(*, scope: str = "user", codex_home: Path | None = None, project_dir: Path | None = None) -> bool:
    home = codex_home or default_codex_home()
    target = _target_path(scope, home, project_dir or Path.cwd())
    data = _read_hooks_json(target)
    if data is None:
        return False
    return set(_ai_keeper_hook_positions(data)) == set(HOOK_EVENTS)


def codex_hooks_trust_status(
    *,
    scope: str = "user",
    codex_home: Path | None = None,
    project_dir: Path | None = None,
) -> CodexHookTrustStatus:
    home = codex_home or default_codex_home()
    target = _target_path(scope, home, project_dir or Path.cwd())
    config_path = _codex_config_path(home)
    data = _read_hooks_json(target)
    if data is None:
        missing_events = HOOK_EVENTS
        return CodexHookTrustStatus(
            installed=False,
            ready=False,
            hooks_path=target,
            config_path=config_path,
            missing_events=missing_events,
            untrusted_events=(),
            disabled_events=(),
        )

    positions = _ai_keeper_hook_positions(data)
    missing_events = tuple(event_name for event_name in HOOK_EVENTS if event_name not in positions)
    state = _codex_hook_state(config_path)
    untrusted_events: list[str] = []
    disabled_events: list[str] = []
    for event_name in HOOK_EVENTS:
        position = positions.get(event_name)
        if position is None:
            continue
        state_key = _codex_hook_state_key(target, event_name, position[0], position[1])
        event_state = state.get(state_key, {})
        if not isinstance(event_state, dict) or not event_state.get("trusted_hash"):
            untrusted_events.append(event_name)
            continue
        if event_state.get("enabled") is False:
            disabled_events.append(event_name)

    installed = not missing_events
    ready = installed and not untrusted_events and not disabled_events
    return CodexHookTrustStatus(
        installed=installed,
        ready=ready,
        hooks_path=target,
        config_path=config_path,
        missing_events=missing_events,
        untrusted_events=tuple(untrusted_events),
        disabled_events=tuple(disabled_events),
    )


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
AIKEEPER_BIN="$PWD/.venv/bin/aikeeper"
if [[ -x "$AIKEEPER_BIN" ]]; then
  "$AIKEEPER_BIN" audit distribution --json >/dev/null
else
  aikeeper audit distribution --json >/dev/null
fi
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
AIKEEPER_BIN="$PWD/.venv/bin/aikeeper"
if [[ -x "$AIKEEPER_BIN" ]]; then
  "$AIKEEPER_BIN" audit distribution --json >/dev/null
else
  aikeeper audit distribution --json >/dev/null
fi
echo "AI Keeper: author history private marker audit"
PYTHON_BIN="$PWD/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$(command -v python3 || command -v python)"
fi
"$PYTHON_BIN" - <<'PY'
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

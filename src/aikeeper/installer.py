from __future__ import annotations

import json
import shlex
import shutil
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

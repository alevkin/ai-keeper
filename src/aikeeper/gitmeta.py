from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


JIRA_RE = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]+-\d+)(?![A-Z0-9])", re.IGNORECASE)
GH_RE = re.compile(r"(?:^|[-_/])(GH-\d+|ISSUE-\d+|PR-\d+|#\d+)(?:$|[-_/])", re.IGNORECASE)


@dataclass(frozen=True)
class GitMetadata:
    root_path: Path
    branch: str | None
    origin_url: str | None
    sha: str | None


def _git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value or None


def get_git_metadata(cwd: Path | str) -> GitMetadata:
    path = Path(cwd).expanduser()
    root = _git(path, "rev-parse", "--show-toplevel")
    root_path = Path(root) if root else path
    return GitMetadata(
        root_path=root_path,
        branch=_git(root_path, "branch", "--show-current") if root else None,
        origin_url=_git(root_path, "config", "--get", "remote.origin.url") if root else None,
        sha=_git(root_path, "rev-parse", "HEAD") if root else None,
    )


def parse_issue_id(branch: str | None) -> str | None:
    if not branch:
        return None
    jira = JIRA_RE.search(branch)
    if jira:
        return jira.group(1).upper()
    gh = GH_RE.search(branch)
    if gh:
        return gh.group(1).upper()
    return None


def task_identity(branch: str | None) -> tuple[str, str, str | None, str]:
    issue_id = parse_issue_id(branch)
    if issue_id:
        return issue_id, "git_branch", issue_id, issue_id
    if branch:
        return branch, "git_branch", None, branch
    return "unassigned", "fallback", None, "unassigned"

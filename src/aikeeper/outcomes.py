from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from aikeeper.db import connect, init_db
from aikeeper.gitmeta import get_git_metadata, parse_issue_id, task_identity
from aikeeper.pricing import estimate_event_cost_usd
from aikeeper.storage import ensure_project_and_task
from aikeeper.timeutils import now_ms


OUTCOME_STATUSES = {"candidate", "useful", "partial", "discarded", "verified", "blocked"}
OUTCOME_TYPES = {"code", "test", "docs", "release", "diagnosis", "decision", "unknown"}
CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|docs|test|refactor|perf|build|ci|chore|revert)(\([A-Za-z0-9._/-]+\))?!?: .+"
)


def _git(cwd: Path | str, *args: str) -> str | None:
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


def _row_int(row: Any, key: str) -> int:
    try:
        return int(row[key] or 0)
    except (KeyError, TypeError, ValueError):
        return 0


def _estimate_rows_cost(rows: list[Any]) -> float:
    total = 0.0
    for row in rows:
        cost = estimate_event_cost_usd(
            str(row["model"] or "unknown"),
            input_tokens=_row_int(row, "input_tokens"),
            cached_input_tokens=_row_int(row, "cached_input_tokens"),
            output_tokens=_row_int(row, "output_tokens"),
            cache_creation_input_tokens=_row_int(row, "cache_creation_input_tokens"),
            cache_creation_1h_input_tokens=_row_int(row, "cache_creation_1h_input_tokens"),
        )
        if cost is not None:
            total += cost
    return round(total, 6)


def _task_metrics(con, task_id: int) -> dict[str, int | float]:
    rows = con.execute(
        """
        select s.model, te.input_tokens, te.cached_input_tokens,
               te.cache_creation_input_tokens, te.cache_creation_1h_input_tokens,
               te.output_tokens, te.total_tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where s.task_id = ?
        """,
        (task_id,),
    ).fetchall()
    return {
        "tokens": sum(_row_int(row, "total_tokens") for row in rows),
        "estimated_cost_usd": _estimate_rows_cost(rows),
    }


def _ensure_task_for_cwd(con, *, cwd: Path | str, task_key: str | None = None, seen_ms: int | None = None) -> dict:
    seen = seen_ms or now_ms()
    project_id, detected_task_id, branch, origin, sha, root_path = ensure_project_and_task(con, cwd=cwd, seen_ms=seen)
    if not task_key:
        task = con.execute("select * from tasks where id = ?", (detected_task_id,)).fetchone()
        return {
            "project_id": project_id,
            "task_id": detected_task_id,
            "task_key": task["task_key"],
            "display_name": task["display_name"],
            "branch": branch,
            "origin": origin,
            "sha": sha,
            "root_path": root_path,
        }

    issue_id = parse_issue_id(task_key)
    display_name = issue_id or task_key
    con.execute(
        """
        insert into tasks(project_id, task_key, source, git_branch, issue_id, display_name, first_seen_ms, last_seen_ms)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(project_id, task_key) do update set
            source = excluded.source,
            git_branch = coalesce(excluded.git_branch, tasks.git_branch),
            issue_id = coalesce(excluded.issue_id, tasks.issue_id),
            display_name = excluded.display_name,
            last_seen_ms = max(tasks.last_seen_ms, excluded.last_seen_ms)
        """,
        (project_id, task_key, "manual", branch, issue_id, display_name, seen, seen),
    )
    task_id = con.execute(
        "select id from tasks where project_id = ? and task_key = ?",
        (project_id, task_key),
    ).fetchone()[0]
    return {
        "project_id": project_id,
        "task_id": task_id,
        "task_key": task_key,
        "display_name": display_name,
        "branch": branch,
        "origin": origin,
        "sha": sha,
        "root_path": root_path,
    }


def git_commit_metadata(cwd: Path | str, commit_ref: str = "HEAD") -> dict[str, Any]:
    root = Path(cwd).expanduser()
    sha = _git(root, "rev-parse", commit_ref)
    branch = _git(root, "branch", "--show-current")
    shortstat = _git(root, "show", "--shortstat", "--format=", commit_ref) or ""
    changed_files = insertions = deletions = 0
    files_match = re.search(r"(\d+) files? changed", shortstat)
    insertions_match = re.search(r"(\d+) insertions?", shortstat)
    deletions_match = re.search(r"(\d+) deletions?", shortstat)
    if files_match:
        changed_files = int(files_match.group(1))
    if insertions_match:
        insertions = int(insertions_match.group(1))
    if deletions_match:
        deletions = int(deletions_match.group(1))
    subject = _git(root, "log", "-1", "--pretty=%s", commit_ref) or ""
    return {
        "commit_sha": sha,
        "git_branch": branch,
        "changed_files": changed_files,
        "insertions": insertions,
        "deletions": deletions,
        "conventional_commit": bool(CONVENTIONAL_RE.match(subject)),
    }


def _confidence(status: str, commit_sha: str | None, source: str) -> str:
    if status == "verified" or (status == "useful" and commit_sha):
        return "high"
    if source == "git_commit" or commit_sha:
        return "medium"
    return "low"


def record_outcome(
    db_path: Path | str,
    *,
    cwd: Path | str,
    task_key: str | None = None,
    status: str = "useful",
    outcome_type: str = "code",
    source: str = "manual",
    display_name: str | None = None,
    commit_ref: str = "HEAD",
    created_at_ms: int | None = None,
) -> dict:
    if status not in OUTCOME_STATUSES:
        raise ValueError(f"status must be one of {', '.join(sorted(OUTCOME_STATUSES))}")
    if outcome_type not in OUTCOME_TYPES:
        raise ValueError(f"type must be one of {', '.join(sorted(OUTCOME_TYPES))}")
    timestamp = created_at_ms or now_ms()
    with connect(db_path) as con:
        init_db(con)
        task = _ensure_task_for_cwd(con, cwd=cwd, task_key=task_key, seen_ms=timestamp)
        git = git_commit_metadata(task["root_path"], commit_ref=commit_ref)
        commit_sha = git["commit_sha"]
        outcome_key = str(commit_sha[:12] if commit_sha else f"{task['task_key']}:{timestamp}")
        metrics = _task_metrics(con, int(task["task_id"]))
        label = display_name or f"{task['display_name']} outcome"
        confidence = _confidence(status, commit_sha, source)
        meta = {
            "commit_ref": commit_ref,
            "conventional_commit": git["conventional_commit"],
            "metadata_only": True,
        }
        con.execute(
            """
            insert into outcomes(
                project_id, task_id, outcome_key, source, status, confidence, outcome_type,
                display_name, git_branch, commit_sha, changed_files, insertions, deletions,
                tokens, estimated_cost_usd, created_at_ms, updated_at_ms, completed_at_ms, meta_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(task_id, outcome_key) do update set
                source = excluded.source,
                status = excluded.status,
                confidence = excluded.confidence,
                outcome_type = excluded.outcome_type,
                display_name = excluded.display_name,
                git_branch = coalesce(excluded.git_branch, outcomes.git_branch),
                commit_sha = coalesce(excluded.commit_sha, outcomes.commit_sha),
                changed_files = excluded.changed_files,
                insertions = excluded.insertions,
                deletions = excluded.deletions,
                tokens = excluded.tokens,
                estimated_cost_usd = excluded.estimated_cost_usd,
                updated_at_ms = excluded.updated_at_ms,
                completed_at_ms = excluded.completed_at_ms,
                meta_json = excluded.meta_json
            """,
            (
                task["project_id"],
                task["task_id"],
                outcome_key,
                source,
                status,
                confidence,
                outcome_type,
                label,
                git["git_branch"] or task["branch"],
                commit_sha,
                int(git["changed_files"]),
                int(git["insertions"]),
                int(git["deletions"]),
                int(metrics["tokens"]),
                float(metrics["estimated_cost_usd"]),
                timestamp,
                timestamp,
                timestamp if status in {"useful", "partial", "verified", "discarded"} else None,
                json.dumps(meta, sort_keys=True),
            ),
        )
        outcome = con.execute(
            "select * from outcomes where task_id = ? and outcome_key = ?",
            (task["task_id"], outcome_key),
        ).fetchone()
        con.execute(
            """
            insert into outcome_events(outcome_id, event_type, source, status, created_at_ms, commit_sha, meta_json)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                outcome["id"],
                "marked",
                source,
                status,
                timestamp,
                commit_sha,
                json.dumps({"metadata_only": True}, sort_keys=True),
            ),
        )
        con.commit()
        return _outcome_dict(outcome)


def _outcome_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "project_id": int(row["project_id"]),
        "task_id": int(row["task_id"]),
        "outcome_key": row["outcome_key"],
        "source": row["source"],
        "status": row["status"],
        "confidence": row["confidence"],
        "type": row["outcome_type"],
        "display_name": row["display_name"],
        "git_branch": row["git_branch"],
        "commit_sha": row["commit_sha"],
        "changed_files": int(row["changed_files"]),
        "insertions": int(row["insertions"]),
        "deletions": int(row["deletions"]),
        "tokens": int(row["tokens"]),
        "estimated_cost_usd": float(row["estimated_cost_usd"]),
        "updated_at_ms": int(row["updated_at_ms"]),
        "completed_at_ms": int(row["completed_at_ms"]) if row["completed_at_ms"] is not None else None,
    }


def recent_outcomes_for_task(con, task_id: int, *, limit: int = 5) -> list[dict]:
    rows = con.execute(
        """
        select *
        from outcomes
        where task_id = ?
        order by updated_at_ms desc, id desc
        limit ?
        """,
        (task_id, limit),
    ).fetchall()
    return [_outcome_dict(row) for row in rows]


def task_outcome_summary(con, task_id: int) -> dict:
    row = con.execute(
        """
        select count(*) as total,
               sum(case when status in ('useful', 'verified') then 1 else 0 end) as useful,
               sum(case when status = 'candidate' then 1 else 0 end) as candidates,
               sum(case when status = 'discarded' then 1 else 0 end) as discarded
        from outcomes
        where task_id = ?
        """,
        (task_id,),
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "useful": int(row["useful"] or 0),
        "candidates": int(row["candidates"] or 0),
        "discarded": int(row["discarded"] or 0),
    }


def _git_hooks_dir(root_path: Path) -> Path | None:
    hooks = _git(root_path, "rev-parse", "--git-path", "hooks")
    if not hooks:
        return None
    path = Path(hooks)
    return path if path.is_absolute() else root_path / path


def git_hooks_installed(root_path: Path | str) -> bool:
    hooks_dir = _git_hooks_dir(Path(root_path).expanduser())
    if not hooks_dir:
        return False
    required = ("pre-commit", "pre-push", "commit-msg")
    for name in required:
        path = hooks_dir / name
        if not path.exists():
            return False
        try:
            if "AI Keeper" not in path.read_text(encoding="utf-8", errors="replace"):
                return False
        except OSError:
            return False
    return True


def inspect_git_workflow(root_path: Path | str, task_key: str | None = None) -> dict:
    root = Path(root_path).expanduser()
    meta = get_git_metadata(root)
    branch = meta.branch
    subject = _git(root, "log", "-1", "--pretty=%s") or ""
    branch_task_key, _source, _issue_id, _display = task_identity(branch)
    task_is_named = bool(task_key and task_key != "unassigned")
    return {
        "root_path": str(meta.root_path),
        "branch": branch,
        "task_key": task_key,
        "branch_task_key": branch_task_key,
        "branch_has_task_key": bool(task_is_named and branch and task_key and task_key.lower() in branch.lower()),
        "task_is_named": task_is_named,
        "git_hooks_installed": git_hooks_installed(meta.root_path),
        "latest_commit_conventional": bool(CONVENTIONAL_RE.match(subject)),
        "latest_commit_sha": _git(meta.root_path, "rev-parse", "HEAD"),
    }


def suggest_outcome_for_task(con, *, task_id: int, root_path: Path | str, task_key: str) -> dict | None:
    git = git_commit_metadata(root_path)
    commit_sha = git.get("commit_sha")
    if not commit_sha:
        return None
    existing = con.execute(
        "select id from outcomes where task_id = ? and commit_sha = ?",
        (task_id, commit_sha),
    ).fetchone()
    if existing:
        return None
    metrics = _task_metrics(con, task_id)
    if int(metrics["tokens"]) <= 0:
        return None
    confidence = "high" if git.get("conventional_commit") else "medium"
    return {
        "source": "git_commit",
        "status": "candidate",
        "confidence": confidence,
        "task_key": task_key,
        "commit_sha": commit_sha,
        "changed_files": int(git["changed_files"]),
        "insertions": int(git["insertions"]),
        "deletions": int(git["deletions"]),
        "tokens": int(metrics["tokens"]),
        "estimated_cost_usd": float(metrics["estimated_cost_usd"]),
    }


def workflow_harness_state(con, current: dict | None) -> dict:
    empty = {
        "configured": False,
        "status": "learning",
        "coverage": [],
        "gaps": ["No active task yet"],
        "outcome_summary": {"total": 0, "useful": 0, "candidates": 0, "discarded": 0},
        "recent_outcomes": [],
        "suggested_outcome": None,
        "commands": [],
    }
    if not current:
        return empty

    root_path = Path(str(current["root_path"]))
    task_id = int(current["task_id"])
    task_key = str(current["task_key"])
    git = inspect_git_workflow(root_path, task_key=task_key)
    summary = task_outcome_summary(con, task_id)
    recent = recent_outcomes_for_task(con, task_id)
    suggestion = suggest_outcome_for_task(con, task_id=task_id, root_path=root_path, task_key=task_key)
    coverage = [
        {"label": "Named task", "ok": git["task_is_named"], "detail": task_key if git["task_is_named"] else "unassigned"},
        {
            "label": "Task branch",
            "ok": git["branch_has_task_key"],
            "detail": git["branch"] or "no branch",
        },
        {"label": "Git hooks", "ok": git["git_hooks_installed"], "detail": "pre-commit, pre-push, commit-msg"},
        {
            "label": "Conventional commit",
            "ok": git["latest_commit_conventional"],
            "detail": (git["latest_commit_sha"] or "no commit")[:12],
        },
    ]
    gaps = []
    if not git["task_is_named"]:
        gaps.append("Ask which task this session belongs to")
    if git["task_is_named"] and not git["branch_has_task_key"]:
        gaps.append("Use a feature branch that includes the task key")
    if not git["git_hooks_installed"]:
        gaps.append("Install AI Keeper git hooks for workflow guardrails")
    if suggestion:
        gaps.append("Review the suggested outcome candidate")
    elif summary["useful"] == 0 and int(current["total_tokens"]) > 0:
        gaps.append("Mark the useful outcome when this slice is verified")

    status = "ready"
    if gaps:
        status = "attention"
    if summary["useful"] > 0:
        status = "tracked"
    return {
        "configured": True,
        "status": status,
        "coverage": coverage,
        "gaps": gaps,
        "outcome_summary": summary,
        "recent_outcomes": recent,
        "suggested_outcome": suggestion,
        "commands": [
            {
                "label": "Install workflow hooks",
                "command": f"aikeeper install workflow-harness --repo-root {root_path}",
            },
            {
                "label": "Mark outcome done",
                "command": f"aikeeper outcome done --cwd {root_path} --status useful --type code",
            },
        ],
    }


def workflow_harness_state_for_cwd(db_path: Path | str, cwd: Path | str) -> dict:
    with connect(db_path) as con:
        init_db(con)
        task = _ensure_task_for_cwd(con, cwd=cwd)
        current = {
            "task_id": task["task_id"],
            "task_key": task["task_key"],
            "root_path": str(task["root_path"]),
            "total_tokens": int(_task_metrics(con, int(task["task_id"]))["tokens"]),
        }
        con.commit()
        return workflow_harness_state(con, current)

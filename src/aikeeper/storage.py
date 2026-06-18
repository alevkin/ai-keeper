from __future__ import annotations

import sqlite3
from pathlib import Path

from aikeeper.gitmeta import get_git_metadata, task_identity
from aikeeper.timeutils import now_ms


def ensure_project_and_task(
    con: sqlite3.Connection,
    *,
    cwd: Path | str,
    git_branch: str | None = None,
    git_sha: str | None = None,
    git_origin_url: str | None = None,
    seen_ms: int | None = None,
    probe_git: bool = True,
) -> tuple[int, int, str | None, str | None, str | None, Path]:
    seen = seen_ms or now_ms()
    path = Path(cwd).expanduser()
    if probe_git:
        meta = get_git_metadata(path)
        branch = git_branch or meta.branch
        origin = git_origin_url or meta.origin_url
        sha = git_sha or meta.sha
        root_path = meta.root_path
    else:
        branch = git_branch
        origin = git_origin_url
        sha = git_sha
        root_path = path
    name = root_path.name or str(root_path)

    con.execute(
        """
        insert into projects(root_path, name, git_origin, first_seen_ms, last_seen_ms)
        values (?, ?, ?, ?, ?)
        on conflict(root_path) do update set
            name = excluded.name,
            git_origin = coalesce(excluded.git_origin, projects.git_origin),
            last_seen_ms = max(projects.last_seen_ms, excluded.last_seen_ms)
        """,
        (str(root_path), name, origin, seen, seen),
    )
    project_id = con.execute("select id from projects where root_path = ?", (str(root_path),)).fetchone()[0]

    task_key, source, issue_id, display_name = task_identity(branch)
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
        (project_id, task_key, source, branch, issue_id, display_name, seen, seen),
    )
    task_id = con.execute(
        "select id from tasks where project_id = ? and task_key = ?",
        (project_id, task_key),
    ).fetchone()[0]
    return project_id, task_id, branch, origin, sha, root_path


def upsert_session(
    con: sqlite3.Connection,
    *,
    provider: str,
    session_id: str,
    cwd: Path | str,
    transcript_path: Path | str | None,
    model: str | None,
    model_provider: str | None,
    source: str | None,
    git_sha: str | None,
    git_branch: str | None,
    git_origin_url: str | None,
    created_at_ms: int,
    updated_at_ms: int,
    total_tokens: int = 0,
    probe_git: bool = True,
) -> int:
    project_id, task_id, branch, origin, detected_sha, _root_path = ensure_project_and_task(
        con,
        cwd=cwd,
        git_sha=git_sha,
        git_branch=git_branch,
        git_origin_url=git_origin_url,
        seen_ms=updated_at_ms,
        probe_git=probe_git,
    )
    con.execute(
        """
        insert into sessions(
            provider, session_id, transcript_path, cwd, model, model_provider,
            source, project_id, task_id, git_sha, git_branch, git_origin_url,
            created_at_ms, updated_at_ms, total_tokens, last_seen_ms
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(provider, session_id) do update set
            transcript_path = coalesce(excluded.transcript_path, sessions.transcript_path),
            cwd = excluded.cwd,
            model = coalesce(excluded.model, sessions.model),
            model_provider = coalesce(excluded.model_provider, sessions.model_provider),
            source = coalesce(excluded.source, sessions.source),
            project_id = excluded.project_id,
            task_id = excluded.task_id,
            git_sha = coalesce(excluded.git_sha, sessions.git_sha),
            git_branch = coalesce(excluded.git_branch, sessions.git_branch),
            git_origin_url = coalesce(excluded.git_origin_url, sessions.git_origin_url),
            updated_at_ms = max(sessions.updated_at_ms, excluded.updated_at_ms),
            total_tokens = max(sessions.total_tokens, excluded.total_tokens),
            last_seen_ms = max(sessions.last_seen_ms, excluded.last_seen_ms)
        """,
        (
            provider,
            session_id,
            str(transcript_path) if transcript_path else None,
            str(Path(cwd).expanduser()),
            model,
            model_provider,
            source,
            project_id,
            task_id,
            detected_sha,
            branch,
            origin,
            created_at_ms,
            updated_at_ms,
            total_tokens,
            updated_at_ms,
        ),
    )
    return con.execute(
        "select id from sessions where provider = ? and session_id = ?",
        (provider, session_id),
    ).fetchone()[0]

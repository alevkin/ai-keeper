from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from aikeeper.db import connect, init_db
from aikeeper.gitmeta import get_git_metadata, task_identity
from aikeeper.timeutils import now_ms as current_now_ms
from aikeeper.timeutils import utc_day_start_ms, utc_week_start_ms


def _sum_tokens_since(con, session_filter: str, params: tuple, since_ms: int) -> int:
    row = con.execute(
        f"""
        select coalesce(sum(te.total_tokens), 0) as tokens
        from token_events te
        join sessions s on s.id = te.session_pk
        where {session_filter} and te.timestamp_ms >= ?
        """,
        (*params, since_ms),
    ).fetchone()
    return int(row["tokens"])


def _sum_tokens_between(con, start_ms: int, end_ms: int) -> int:
    row = con.execute(
        """
        select coalesce(sum(total_tokens), 0) as tokens
        from token_events
        where timestamp_ms >= ? and timestamp_ms < ?
        """,
        (start_ms, end_ms),
    ).fetchone()
    return int(row["tokens"])


def _date_label(day_start_ms: int) -> str:
    return datetime.fromtimestamp(day_start_ms / 1000, tz=UTC).date().isoformat()


def _daily_tokens(con, now_ms: int, days: int = 7) -> list[dict]:
    day_start = utc_day_start_ms(now_ms)
    day_ms = 86_400_000
    rows = []
    for index in range(days - 1, -1, -1):
        start = day_start - index * day_ms
        end = start + day_ms
        rows.append({"date": _date_label(start), "tokens": _sum_tokens_between(con, start, end)})
    return rows


def _current_activity(con) -> dict | None:
    session = con.execute(
        """
        select s.id, s.session_id, s.cwd, s.model, s.updated_at_ms, s.total_tokens,
               p.id as project_id, p.name as project_name, p.root_path,
               t.id as task_id, t.task_key, t.display_name as task_name,
               (
                   select te.total_tokens
                   from token_events te
                   where te.session_pk = s.id
                   order by te.sequence desc
                   limit 1
               ) as last_turn_tokens
        from sessions s
        join projects p on p.id = s.project_id
        join tasks t on t.id = s.task_id
        order by s.updated_at_ms desc, s.id desc
        limit 1
        """
    ).fetchone()
    if not session:
        return None
    data = dict(session)
    data["session_label"] = str(data["session_id"])[:8]
    data["last_turn_tokens"] = int(data["last_turn_tokens"] or 0)
    data["total_tokens"] = int(data["total_tokens"])
    return data


def status_for_cwd(db_path: Path | str, cwd: Path | str, now_ms: int | None = None) -> dict:
    now = now_ms or current_now_ms()
    day_start = utc_day_start_ms(now)
    meta = get_git_metadata(cwd)
    task_key, _source, issue_id, display_name = task_identity(meta.branch)

    with connect(db_path) as con:
        init_db(con)
        session = con.execute(
            """
            select s.*, p.name as project_name, p.root_path, t.task_key, t.display_name as task_name
            from sessions s
            join projects p on p.id = s.project_id
            join tasks t on t.id = s.task_id
            where s.cwd = ? or p.root_path = ?
            order by s.updated_at_ms desc, s.id desc
            limit 1
            """,
            (str(Path(cwd).expanduser()), str(meta.root_path)),
        ).fetchone()
        if not session:
            return {
                "project": {"name": meta.root_path.name, "root_path": str(meta.root_path), "today_tokens": 0},
                "task": {"task_key": task_key, "display_name": display_name, "issue_id": issue_id, "today_tokens": 0},
                "session": {"session_id": None, "total_tokens": 0, "last_turn_tokens": 0},
            }

        last_turn = con.execute(
            """
            select total_tokens from token_events
            where session_pk = ?
            order by sequence desc
            limit 1
            """,
            (session["id"],),
        ).fetchone()

        project_today = _sum_tokens_since(con, "s.project_id = ?", (session["project_id"],), day_start)
        task_today = _sum_tokens_since(con, "s.task_id = ?", (session["task_id"],), day_start)
        return {
            "project": {
                "id": session["project_id"],
                "name": session["project_name"],
                "root_path": session["root_path"],
                "today_tokens": project_today,
            },
            "task": {
                "id": session["task_id"],
                "task_key": session["task_key"],
                "display_name": session["task_name"],
                "issue_id": issue_id,
                "today_tokens": task_today,
            },
            "session": {
                "id": session["id"],
                "session_id": session["session_id"],
                "total_tokens": int(session["total_tokens"]),
                "last_turn_tokens": int(last_turn["total_tokens"]) if last_turn else 0,
            },
        }


def overview(db_path: Path | str, now_ms: int | None = None) -> dict:
    now = now_ms or current_now_ms()
    day_start = utc_day_start_ms(now)
    week_start = utc_week_start_ms(now)
    with connect(db_path) as con:
        init_db(con)
        total_tokens = con.execute("select coalesce(sum(total_tokens), 0) as tokens from token_events").fetchone()
        today_tokens = con.execute(
            "select coalesce(sum(total_tokens), 0) as tokens from token_events where timestamp_ms >= ?",
            (day_start,),
        ).fetchone()
        week_tokens = con.execute(
            "select coalesce(sum(total_tokens), 0) as tokens from token_events where timestamp_ms >= ?",
            (week_start,),
        ).fetchone()
        projects = con.execute(
            """
            select p.id, p.name, p.root_path,
                   coalesce(sum(te.total_tokens), 0) as tokens,
                   coalesce(sum(case when te.timestamp_ms >= ? then te.total_tokens else 0 end), 0) as today_tokens
            from projects p
            left join sessions s on s.project_id = p.id
            left join token_events te on te.session_pk = s.id
            group by p.id
            order by tokens desc, p.last_seen_ms desc
            """
            ,
            (day_start,),
        ).fetchall()
        tasks = con.execute(
            """
            select t.id, t.display_name, t.task_key, p.name as project_name,
                   coalesce(sum(te.total_tokens), 0) as tokens
            from tasks t
            join projects p on p.id = t.project_id
            left join sessions s on s.task_id = t.id
            left join token_events te on te.session_pk = s.id
            group by t.id
            order by tokens desc, t.last_seen_ms desc
            limit 12
            """
        ).fetchall()
        return {
            "generated_at_ms": now,
            "total_tokens": int(total_tokens["tokens"]),
            "today_tokens": int(today_tokens["tokens"]),
            "week_tokens": int(week_tokens["tokens"]),
            "daily_tokens": _daily_tokens(con, now),
            "current_activity": _current_activity(con),
            "projects": [dict(row) for row in projects],
            "tasks": [dict(row) for row in tasks],
        }


def project_detail(db_path: Path | str, project_id: int) -> dict:
    with connect(db_path) as con:
        init_db(con)
        project = con.execute("select * from projects where id = ?", (project_id,)).fetchone()
        if not project:
            raise KeyError(project_id)
        tasks = con.execute(
            """
            select t.*, coalesce(sum(te.total_tokens), 0) as tokens, count(distinct s.id) as sessions_count
            from tasks t
            left join sessions s on s.task_id = t.id
            left join token_events te on te.session_pk = s.id
            where t.project_id = ?
            group by t.id
            order by tokens desc, t.last_seen_ms desc
            """,
            (project_id,),
        ).fetchall()
        sessions = con.execute(
            """
            select s.*, t.display_name as task_name
            from sessions s
            join tasks t on t.id = s.task_id
            where s.project_id = ?
            order by s.updated_at_ms desc
            limit 50
            """,
            (project_id,),
        ).fetchall()
        return {"project": dict(project), "tasks": [dict(row) for row in tasks], "sessions": [dict(row) for row in sessions]}


def session_detail(db_path: Path | str, session_pk: int) -> dict:
    with connect(db_path) as con:
        init_db(con)
        session = con.execute(
            """
            select s.*, p.name as project_name, t.display_name as task_name
            from sessions s
            join projects p on p.id = s.project_id
            join tasks t on t.id = s.task_id
            where s.id = ?
            """,
            (session_pk,),
        ).fetchone()
        if not session:
            raise KeyError(session_pk)
        events = con.execute(
            """
            select * from token_events
            where session_pk = ?
            order by sequence asc
            """,
            (session_pk,),
        ).fetchall()
        return {"session": dict(session), "events": [dict(row) for row in events]}

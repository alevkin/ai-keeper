from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from aikeeper.db import connect, init_db
from aikeeper.timeutils import now_ms


OUTPUT_TAIL_BYTES = 32_000
TERMINAL_STATUSES = {"ok", "fail"}


def _command_text(command: list[str]) -> str:
    return " ".join(command)


def _row_to_job(row) -> dict[str, Any]:
    command = json.loads(row["command_json"])
    return {
        "id": row["id"],
        "action": row["action"],
        "status": row["status"],
        "command": _command_text(command),
        "command_args": command,
        "cwd": row["cwd"],
        "log_path": row["log_path"],
        "created_at_ms": row["created_at_ms"],
        "started_at_ms": row["started_at_ms"],
        "finished_at_ms": row["finished_at_ms"],
        "exit_code": row["exit_code"],
        "output_tail": row["output_tail"] or "",
        "error": row["error"],
    }


def _tail_text(text: str, limit: int = OUTPUT_TAIL_BYTES) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    return encoded[-limit:].decode("utf-8", errors="replace")


def create_system_job(
    db_path: Path | str,
    *,
    action: str,
    command: list[str],
    cwd: Path | str,
    log_path: Path | str,
    now: int | None = None,
) -> dict[str, Any]:
    created_at = now if now is not None else now_ms()
    with connect(db_path) as con:
        init_db(con)
        cur = con.execute(
            """
            insert into system_jobs(action, status, command_json, cwd, log_path, created_at_ms)
            values (?, ?, ?, ?, ?, ?)
            """,
            (action, "queued", json.dumps(command), str(cwd), str(log_path), created_at),
        )
        job_id = cur.lastrowid
        row = con.execute("select * from system_jobs where id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def get_system_job(db_path: Path | str, job_id: int) -> dict[str, Any]:
    with connect(db_path) as con:
        init_db(con)
        row = con.execute("select * from system_jobs where id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return _row_to_job(row)


def list_system_jobs(db_path: Path | str, *, limit: int = 10) -> list[dict[str, Any]]:
    with connect(db_path) as con:
        init_db(con)
        rows = con.execute(
            "select * from system_jobs order by created_at_ms desc, id desc limit ?",
            (limit,),
        ).fetchall()
    return [_row_to_job(row) for row in rows]


def _mark_running(db_path: Path | str, job_id: int, timestamp_ms: int) -> None:
    with connect(db_path) as con:
        con.execute(
            "update system_jobs set status = ?, started_at_ms = ? where id = ?",
            ("running", timestamp_ms, job_id),
        )


def _mark_finished(
    db_path: Path | str,
    job_id: int,
    *,
    status: str,
    exit_code: int | None,
    output_tail: str,
    error: str | None,
    timestamp_ms: int,
) -> dict[str, Any]:
    with connect(db_path) as con:
        con.execute(
            """
            update system_jobs
            set status = ?, finished_at_ms = ?, exit_code = ?, output_tail = ?, error = ?
            where id = ?
            """,
            (status, timestamp_ms, exit_code, output_tail, error, job_id),
        )
        row = con.execute("select * from system_jobs where id = ?", (job_id,)).fetchone()
    return _row_to_job(row)


def run_system_job(db_path: Path | str, *, job_id: int) -> dict[str, Any]:
    job = get_system_job(db_path, job_id)
    if job["status"] in TERMINAL_STATUSES:
        return job

    _mark_running(db_path, job_id, now_ms())
    log_path = Path(job["log_path"]).expanduser()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    output = ""
    error: str | None = None
    exit_code: int | None = None
    try:
        process = subprocess.run(
            job["command_args"],
            cwd=job["cwd"],
            capture_output=True,
            text=True,
            check=False,
        )
        exit_code = process.returncode
        output = (process.stdout or "") + (process.stderr or "")
        status = "ok" if exit_code == 0 else "fail"
    except Exception as exc:
        status = "fail"
        error = str(exc)
        output = error

    output_tail = _tail_text(output)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {job['command']}\n")
        if output_tail:
            handle.write(output_tail.rstrip() + "\n")
        if error:
            handle.write(f"error: {error}\n")
        handle.write(f"status: {status}\n")

    return _mark_finished(
        db_path,
        job_id,
        status=status,
        exit_code=exit_code,
        output_tail=output_tail,
        error=error,
        timestamp_ms=now_ms(),
    )

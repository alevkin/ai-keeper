from pathlib import Path

from aikeeper.db import connect, init_db
from aikeeper.system_jobs import create_system_job, list_system_jobs, run_system_job


def test_system_job_lifecycle_records_command_output_and_status(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    log_path = tmp_path / "jobs.log"
    with connect(db_path) as con:
        init_db(con)

    job = create_system_job(
        db_path,
        action="diagnostics",
        command=["python", "-c", "print('job ok')"],
        cwd=tmp_path,
        log_path=log_path,
    )

    assert job["status"] == "queued"
    assert job["action"] == "diagnostics"

    finished = run_system_job(db_path, job_id=job["id"])
    jobs = list_system_jobs(db_path)

    assert finished["status"] == "ok"
    assert finished["exit_code"] == 0
    assert "job ok" in finished["output_tail"]
    assert "job ok" in log_path.read_text(encoding="utf-8")
    assert jobs[0]["id"] == job["id"]
    assert jobs[0]["status"] == "ok"
    assert jobs[0]["command"] == "python -c print('job ok')"


def test_system_job_lifecycle_records_failed_command(tmp_path: Path) -> None:
    db_path = tmp_path / "keeper.sqlite"
    log_path = tmp_path / "jobs.log"
    with connect(db_path) as con:
        init_db(con)
    job = create_system_job(
        db_path,
        action="repair",
        command=["python", "-c", "import sys; print('boom'); sys.exit(7)"],
        cwd=tmp_path,
        log_path=log_path,
    )

    finished = run_system_job(db_path, job_id=job["id"])

    assert finished["status"] == "fail"
    assert finished["exit_code"] == 7
    assert "boom" in finished["output_tail"]

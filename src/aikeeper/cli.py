from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console

from aikeeper.audit import audit_privacy
from aikeeper.claude import sync_claude_once
from aikeeper.codex import ExecIngestState, ingest_codex_exec_line, sync_codex_once
from aikeeper.db import connect, init_db
from aikeeper.diagnostics import create_diagnostics_bundle
from aikeeper.exports import export_usage
from aikeeper.health import ingest_health
from aikeeper.hooks import handle_codex_hook
from aikeeper.installer import codex_hooks_installed
from aikeeper.installer import install_codex_hooks
from aikeeper.installer import uninstall_codex_hooks
from aikeeper.launchd import bootstrap_launch_agent
from aikeeper.launchd import default_launch_agent_path
from aikeeper.launchd import launch_agent_status
from aikeeper.launchd import standard_launch_agent_path
from aikeeper.launchd import stop_launch_agent
from aikeeper.launchd import uninstall_launch_agent
from aikeeper.launchd import uses_fallback_launch_agent_path
from aikeeper.launchd import write_launch_agent_plist
from aikeeper.openai_costs import fetch_and_import_costs
from aikeeper.service import status_for_cwd
from aikeeper.service import simulate_model_cost
from aikeeper.settings import DEFAULT_HOST, DEFAULT_PORT, app_home, claude_home, codex_home, default_db_path, ensure_app_home
from aikeeper.web import create_app


console = Console()
app = typer.Typer(help="Local Codex token usage daemon and dashboard.")
daemon_app = typer.Typer(help="Run the local web daemon.")
sync_app = typer.Typer(help="Synchronize provider usage data.")
hook_app = typer.Typer(help="Codex hook entrypoints.")
install_app = typer.Typer(help="Install AI Keeper integrations.")
codex_app = typer.Typer(help="Codex wrapper commands.")
audit_app = typer.Typer(help="Inspect AI Keeper privacy guarantees.")
health_app = typer.Typer(help="Inspect AI Keeper ingest health.")
service_app = typer.Typer(help="Install and control the macOS launchd service.")
uninstall_app = typer.Typer(help="Remove AI Keeper integrations.")
diagnostics_app = typer.Typer(help="Create metadata-only troubleshooting bundles.")
app.add_typer(daemon_app, name="daemon")
app.add_typer(sync_app, name="sync")
app.add_typer(hook_app, name="hook")
app.add_typer(install_app, name="install")
app.add_typer(codex_app, name="codex")
app.add_typer(audit_app, name="audit")
app.add_typer(health_app, name="health")
app.add_typer(service_app, name="service")
app.add_typer(uninstall_app, name="uninstall")
app.add_typer(diagnostics_app, name="diagnostics")


@daemon_app.command("start")
def daemon_start(
    host: Annotated[str, typer.Option()] = DEFAULT_HOST,
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    ensure_app_home()
    with connect(db_path) as con:
        init_db(con)
    console.print(f"AI Keeper listening on http://{host}:{port}")
    uvicorn.run(create_app(db_path=db_path, auto_sync=True), host=host, port=port)


@sync_app.command("codex")
def sync_codex(
    once: Annotated[bool, typer.Option(help="Run one sync pass and exit.")] = True,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    if not once:
        raise typer.BadParameter("Only --once is supported in the MVP.")
    result = sync_codex_once(db_path=db_path, codex_home=codex_home())
    sys.stdout.write(
        json.dumps(
            {"sessions_imported": result.sessions_imported, "token_events_imported": result.token_events_imported},
            indent=2,
        )
        + "\n"
    )


@sync_app.command("claude")
def sync_claude(
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    result = sync_claude_once(db_path=db_path, claude_home=claude_home())
    sys.stdout.write(
        json.dumps(
            {"sessions_imported": result.sessions_imported, "token_events_imported": result.token_events_imported},
            indent=2,
        )
        + "\n"
    )


@sync_app.command("openai-costs")
def sync_openai_costs(
    start_time: Annotated[int, typer.Option(help="Unix seconds start time for the OpenAI Admin Costs API.")],
    end_time: Annotated[int | None, typer.Option()] = None,
    group_by: Annotated[str | None, typer.Option()] = None,
    admin_key_env: Annotated[str, typer.Option()] = "OPENAI_ADMIN_KEY",
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    key = os.environ.get(admin_key_env)
    if not key:
        raise typer.BadParameter(f"{admin_key_env} is not set")
    imported = fetch_and_import_costs(
        db_path,
        admin_key=key,
        start_time=start_time,
        end_time=end_time,
        group_by=group_by,
    )
    sys.stdout.write(json.dumps({"cost_rows_imported": imported}, indent=2) + "\n")


@hook_app.command("codex")
def hook_codex(db_path: Annotated[Path, typer.Option()] = default_db_path()) -> None:
    try:
        payload = json.load(sys.stdin)
        result = handle_codex_hook(payload, db_path=db_path, codex_home=codex_home())
    except Exception as exc:  # Hooks must fail open for Codex.
        result = {"continue": True, "systemMessage": f"AI Keeper hook failed: {exc}"}
    if result:
        sys.stdout.write(json.dumps(result))


@install_app.command("codex-hooks")
def install_codex_hooks_cmd(
    scope: Annotated[str, typer.Option(help="user or project")] = "user",
) -> None:
    target = install_codex_hooks(scope=scope, codex_home=codex_home(), project_dir=Path.cwd())
    console.print(f"Installed Codex hooks at {target}")


@install_app.command("all")
def install_all(
    host: Annotated[str, typer.Option()] = DEFAULT_HOST,
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    db_path: Annotated[Path | None, typer.Option()] = None,
    scope: Annotated[str, typer.Option(help="user or project")] = "user",
    plist_path: Annotated[Path | None, typer.Option()] = None,
    start: Annotated[bool, typer.Option(help="Bootstrap and start the LaunchAgent after writing it.")] = True,
) -> None:
    db = db_path or default_db_path()
    ensure_app_home()
    with connect(db) as con:
        init_db(con)
    hooks_target = install_codex_hooks(scope=scope, codex_home=codex_home(), project_dir=Path.cwd())
    service_target = write_launch_agent_plist(plist_path=plist_path, host=host, port=port, db_path=db)
    if start:
        bootstrap_launch_agent(service_target)

    console.print(f"Initialized AI Keeper database at {db}")
    console.print(f"Installed Codex hooks at {hooks_target}")
    if start:
        console.print(f"Installed and started AI Keeper LaunchAgent at {service_target}")
    else:
        console.print(f"Installed AI Keeper LaunchAgent at {service_target}")
    console.print(f"Dashboard: http://{host}:{port}")
    if uses_fallback_launch_agent_path(service_target):
        console.print(
            f"Note: {standard_launch_agent_path()} is not writable, so AI Keeper used a fallback plist path."
        )


@uninstall_app.command("all")
def uninstall_all(
    scope: Annotated[str, typer.Option(help="user or project")] = "user",
    plist_path: Annotated[Path | None, typer.Option()] = None,
) -> None:
    service_target = uninstall_launch_agent(plist_path=plist_path)
    hooks_target = uninstall_codex_hooks(scope=scope, codex_home=codex_home(), project_dir=Path.cwd())
    console.print(f"Removed AI Keeper LaunchAgent at {service_target}")
    console.print(f"Removed AI Keeper Codex hooks from {hooks_target}")
    console.print(f"Kept AI Keeper data at {default_db_path()}")


@service_app.command("install")
def service_install(
    host: Annotated[str, typer.Option()] = DEFAULT_HOST,
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
    plist_path: Annotated[Path | None, typer.Option()] = None,
    start: Annotated[bool, typer.Option(help="Bootstrap and start the LaunchAgent after writing it.")] = True,
) -> None:
    target = write_launch_agent_plist(plist_path=plist_path, host=host, port=port, db_path=db_path)
    if start:
        bootstrap_launch_agent(target)
        console.print(f"Installed and started AI Keeper LaunchAgent at {target}")
    else:
        console.print(f"Installed AI Keeper LaunchAgent at {target}")
    if uses_fallback_launch_agent_path(target):
        console.print(
            f"Note: {standard_launch_agent_path()} is not writable, so AI Keeper used a fallback plist path."
        )


@service_app.command("start")
def service_start() -> None:
    target = default_launch_agent_path()
    if not target.exists():
        raise typer.BadParameter(f"LaunchAgent plist does not exist: {target}. Run `aikeeper service install` first.")
    bootstrap_launch_agent(target)
    console.print("Started AI Keeper LaunchAgent.")


@service_app.command("stop")
def service_stop() -> None:
    result = stop_launch_agent()
    if result.returncode == 0:
        console.print("Stopped AI Keeper LaunchAgent.")
    else:
        console.print("AI Keeper LaunchAgent was not loaded.")


@service_app.command("restart")
def service_restart() -> None:
    target = default_launch_agent_path()
    if not target.exists():
        raise typer.BadParameter(f"LaunchAgent plist does not exist: {target}. Run `aikeeper service install` first.")
    bootstrap_launch_agent(target)
    console.print("Restarted AI Keeper LaunchAgent.")


@service_app.command("uninstall")
def service_uninstall(plist_path: Annotated[Path | None, typer.Option()] = None) -> None:
    target = uninstall_launch_agent(plist_path=plist_path)
    console.print(f"Removed AI Keeper LaunchAgent at {target}")


@service_app.command("status")
def service_status(
    host: Annotated[str, typer.Option()] = DEFAULT_HOST,
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    plist_path: Annotated[Path | None, typer.Option()] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    data = launch_agent_status(host=host, port=port, plist_path=plist_path)
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    state = "loaded" if data["loaded"] else "not loaded"
    health = "healthy" if data["ping"]["ok"] else "not responding"
    console.print(f"AI Keeper service: {state}, {health} at {data['url']}")
    console.print(f"plist: {data['plist_path']}")


@app.command("status")
def status(
    cwd: Annotated[Path, typer.Option()] = Path.cwd(),
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    data = status_for_cwd(db_path, cwd)
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    console.print(
        f"AI Keeper: session {data['session']['total_tokens']} tokens, "
        f"task today {data['task']['today_tokens']}, "
        f"project today {data['project']['today_tokens']}"
    )


@audit_app.command("privacy")
def audit_privacy_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    data = audit_privacy(db_path)
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    if data["metadata_only"]:
        console.print(
            f"Privacy audit passed: {data['tables_checked']} tables, "
            f"{data['text_columns_checked']} text columns checked."
        )
        return
    console.print(f"Privacy audit failed: {len(data['findings'])} finding(s).")
    for finding in data["findings"]:
        console.print(f"- {finding['table']}.{finding['column']}: {finding['reason']}")


@health_app.command("ingest")
def health_ingest_cmd(
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    data = ingest_health(db_path)
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    console.print(
        f"Ingest health: {data['status']} · "
        f"{data['sessions']['total']} sessions · "
        f"{data['token_events']['total']} token events · "
        f"{data['transcripts']['missing']} missing transcript(s)"
    )
    for issue in data["issues"]:
        console.print(f"- {issue}")
    for item in data["transcripts"]["missing_paths"][:5]:
        console.print(f"  missing transcript: {item['path']} ({item['session_id']})")
    for source in data["ingest_state"]["problem_sources"][:5]:
        state = "missing" if source["exists"] is False else "lagging" if source["lagging"] else "ok"
        console.print(f"  {state} source: {source['path'] or source['source_key']}")


@diagnostics_app.command("bundle")
def diagnostics_bundle(
    host: Annotated[str, typer.Option()] = DEFAULT_HOST,
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    db_path: Annotated[Path | None, typer.Option()] = None,
    output_dir: Annotated[Path | None, typer.Option()] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    archive = create_diagnostics_bundle(
        db_path=db_path or default_db_path(),
        output_dir=output_dir,
        host=host,
        port=port,
    )
    data = {"archive_path": str(archive), "metadata_only": True}
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    console.print(f"Created AI Keeper diagnostics bundle: {archive}")


def _doctor_check(name: str, status: str, detail: str, fix: str | None = None) -> dict[str, str | None]:
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def _overall_status(checks: list[dict[str, str | None]]) -> str:
    statuses = {check["status"] for check in checks}
    return "fail" if "fail" in statuses else "warn" if "warn" in statuses else "ok"


def _doctor_data(*, host: str, port: int, db: Path, scope: str) -> dict:
    home = app_home()
    checks: list[dict[str, str | None]] = []

    if home.exists() and os.access(home, os.W_OK):
        checks.append(_doctor_check("app_home", "ok", str(home)))
    elif home.exists():
        checks.append(_doctor_check("app_home", "fail", f"{home} is not writable", "Fix directory ownership/permissions."))
    else:
        checks.append(_doctor_check("app_home", "warn", f"{home} does not exist", "Run `aikeeper install all`."))

    if db.exists():
        try:
            with connect(db) as con:
                init_db(con)
            checks.append(_doctor_check("database", "ok", str(db)))
        except Exception as exc:
            checks.append(_doctor_check("database", "fail", f"{db}: {exc}", "Check SQLite file permissions."))
    else:
        checks.append(_doctor_check("database", "warn", f"{db} does not exist", "Run `aikeeper install all`."))

    if codex_hooks_installed(scope=scope, codex_home=codex_home(), project_dir=Path.cwd()):
        checks.append(_doctor_check("codex_hooks", "ok", f"{scope} hooks installed"))
    else:
        checks.append(
            _doctor_check("codex_hooks", "warn", f"{scope} hooks are missing", f"Run `aikeeper install codex-hooks --scope {scope}`.")
        )

    service = launch_agent_status(host=host, port=port, plist_path=default_launch_agent_path())
    if service["plist_exists"] and service["loaded"]:
        checks.append(_doctor_check("launch_agent", "ok", str(service["plist_path"])))
    elif service["plist_exists"]:
        checks.append(_doctor_check("launch_agent", "warn", "LaunchAgent exists but is not loaded", "Run `aikeeper service start`."))
    else:
        checks.append(_doctor_check("launch_agent", "warn", "LaunchAgent plist is missing", "Run `aikeeper service install`."))

    if service["ping"]["ok"]:
        checks.append(_doctor_check("dashboard", "ok", service["url"]))
    else:
        checks.append(_doctor_check("dashboard", "warn", f"{service['url']} is not responding", "Run `aikeeper service restart`."))

    return {"status": _overall_status(checks), "checks": checks, "service": service}


def _run_doctor_fixes(*, host: str, port: int, db: Path, scope: str) -> list[dict[str, str]]:
    fixes: list[dict[str, str]] = []
    home = app_home()
    if not home.exists():
        ensure_app_home()
        fixes.append({"name": "app_home", "detail": str(home)})

    if not db.exists():
        with connect(db) as con:
            init_db(con)
        fixes.append({"name": "database", "detail": str(db)})

    if not codex_hooks_installed(scope=scope, codex_home=codex_home(), project_dir=Path.cwd()):
        target = install_codex_hooks(scope=scope, codex_home=codex_home(), project_dir=Path.cwd())
        fixes.append({"name": "codex_hooks", "detail": str(target)})

    service = launch_agent_status(host=host, port=port, plist_path=default_launch_agent_path())
    if not service["plist_exists"] or not service["loaded"] or not service["ping"]["ok"]:
        target = write_launch_agent_plist(host=host, port=port, db_path=db)
        bootstrap_launch_agent(target)
        fixes.append({"name": "launch_agent", "detail": str(target)})
    return fixes


@app.command("doctor")
def doctor(
    host: Annotated[str, typer.Option()] = DEFAULT_HOST,
    port: Annotated[int, typer.Option()] = DEFAULT_PORT,
    db_path: Annotated[Path | None, typer.Option()] = None,
    scope: Annotated[str, typer.Option(help="user or project")] = "user",
    fix: Annotated[bool, typer.Option("--fix", help="Repair missing DB, Codex hooks, and LaunchAgent when possible.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON.")] = False,
) -> None:
    db = db_path or default_db_path()
    fixes = _run_doctor_fixes(host=host, port=port, db=db, scope=scope) if fix else []
    data = _doctor_data(host=host, port=port, db=db, scope=scope)
    data["fixes"] = fixes
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return

    console.print(f"AI Keeper doctor: {data['status']}")
    for fix_item in fixes:
        console.print(f"fixed {fix_item['name']}: {fix_item['detail']}")
    for check in data["checks"]:
        line = f"- {check['name']}: {check['status']} - {check['detail']}"
        if check["fix"]:
            line += f" ({check['fix']})"
        console.print(line)


@app.command("simulate")
def simulate(
    target_model: Annotated[str, typer.Option()],
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
) -> None:
    sys.stdout.write(json.dumps(simulate_model_cost(db_path, target_model), indent=2) + "\n")


@app.command("export")
def export(
    fmt: Annotated[str, typer.Option("--format")] = "markdown",
    output: Annotated[Path | None, typer.Option()] = None,
    db_path: Annotated[Path, typer.Option()] = default_db_path(),
    budget_path: Annotated[Path | None, typer.Option()] = None,
) -> None:
    text = export_usage(db_path, fmt, budget_path=budget_path)
    if output:
        output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


@codex_app.command(
    "exec",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def codex_exec(ctx: typer.Context, db_path: Annotated[Path, typer.Option()] = default_db_path()) -> None:
    command = ["codex", "exec", "--json", *ctx.args]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True)
    assert process.stdout is not None
    with connect(db_path) as con:
        init_db(con)
    state = ExecIngestState()
    for line in process.stdout:
        sys.stdout.write(line)
        state = ingest_codex_exec_line(db_path, line, cwd=Path.cwd(), state=state)
    raise typer.Exit(process.wait())


def main() -> None:
    app()

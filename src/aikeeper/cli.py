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
from aikeeper.exports import export_usage
from aikeeper.health import ingest_health
from aikeeper.hooks import handle_codex_hook
from aikeeper.installer import install_codex_hooks
from aikeeper.openai_costs import fetch_and_import_costs
from aikeeper.service import status_for_cwd
from aikeeper.service import simulate_model_cost
from aikeeper.settings import DEFAULT_HOST, DEFAULT_PORT, claude_home, codex_home, default_db_path, ensure_app_home
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
app.add_typer(daemon_app, name="daemon")
app.add_typer(sync_app, name="sync")
app.add_typer(hook_app, name="hook")
app.add_typer(install_app, name="install")
app.add_typer(codex_app, name="codex")
app.add_typer(audit_app, name="audit")
app.add_typer(health_app, name="health")


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

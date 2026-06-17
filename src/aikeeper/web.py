from __future__ import annotations

import shlex
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aikeeper.audit import audit_privacy
from aikeeper.budgets import LIMIT_DEFINITIONS, load_budget_config_from_db, save_budget_settings
from aikeeper.codex import sync_codex_once
from aikeeper.db import connect, init_db
from aikeeper.diagnostics import append_system_action_log, create_diagnostics_bundle, diagnostics_overview, resolve_diagnostics_bundle
from aikeeper.health import ingest_health
from aikeeper.installer import codex_hooks_installed
from aikeeper.launchd import default_launch_agent_path, launch_agent_status, project_root
from aikeeper.service import overview, project_detail, session_detail, simulate_model_cost
from aikeeper.settings import DEFAULT_HOST, DEFAULT_PORT, app_home
from aikeeper.settings import codex_home as default_codex_home
from aikeeper.settings import default_db_path
from aikeeper.version import get_app_version


PACKAGE_DIR = Path(__file__).parent
SYSTEM_ACTIONS = (
    {"key": "repair", "label": "Repair", "description": "Run doctor --fix in the background."},
    {"key": "reinstall", "label": "Reinstall", "description": "Reinstall hooks and the LaunchAgent."},
    {"key": "restart", "label": "Restart", "description": "Restart the LaunchAgent service."},
    {"key": "diagnostics", "label": "Diagnostics", "description": "Create a metadata-only diagnostics bundle."},
)
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))


def format_tokens(value: int | None) -> str:
    return f"{int(value or 0):,}"


def compact_tokens(value: int | None) -> str:
    number = int(value or 0)
    if abs(number) >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if abs(number) >= 1_000_000:
        return f"{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{number / 1_000:.1f}K"
    return str(number)


def format_usd(value: float | None) -> str:
    amount = float(value or 0)
    if 0 < abs(amount) < 0.01:
        return f"${amount:,.4f}"
    return f"${amount:,.2f}"


def compact_usd(value: float | None) -> str:
    amount = float(value or 0)
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:.2f}M"
    if abs(amount) >= 1_000:
        return f"${amount / 1_000:.2f}K"
    return format_usd(amount)


def compact_per_minute(value: float | None) -> str:
    amount = float(value or 0)
    if abs(amount) >= 1_000_000:
        return f"{amount / 1_000_000:.2f}M/min"
    if abs(amount) >= 1_000:
        return f"{amount / 1_000:.1f}K/min"
    if amount.is_integer():
        return f"{int(amount)}/min"
    return f"{amount:.1f}/min"


def usd_per_minute(value: float | None) -> str:
    return f"{format_usd(value)}/min"


def percent(value: float | None) -> str:
    return f"{float(value or 0) * 100:.1f}%"


def signed_percent(value: float | None) -> str:
    return f"{float(value or 0) * 100:+.1f}%"


templates.env.filters["tokens"] = format_tokens
templates.env.filters["compact_tokens"] = compact_tokens
templates.env.filters["usd"] = format_usd
templates.env.filters["compact_usd"] = compact_usd
templates.env.filters["per_minute"] = compact_per_minute
templates.env.filters["usd_per_minute"] = usd_per_minute
templates.env.filters["percent"] = percent
templates.env.filters["signed_percent"] = signed_percent


def _safe_launch_agent_status(*, host: str, port: int) -> dict:
    try:
        return launch_agent_status(host=host, port=port, plist_path=default_launch_agent_path())
    except Exception as exc:
        target = default_launch_agent_path()
        return {
            "label": "com.aikeeper.daemon",
            "plist_path": str(target),
            "plist_exists": target.exists(),
            "loaded": False,
            "service_target": None,
            "url": f"http://{host}:{port}",
            "ping": {"ok": False, "error": str(exc)},
            "launchctl_returncode": None,
            "launchctl_stdout": "",
            "launchctl_stderr": str(exc),
        }


def _system_status(*, db: Path, home: Path, host: str, port: int) -> dict:
    service = _safe_launch_agent_status(host=host, port=port)
    app_dir = app_home()
    hooks_ok = codex_hooks_installed(scope="user", codex_home=home, project_dir=Path.cwd())
    db_ok = db.exists()
    checks = [
        {"name": "Database", "status": "ok" if db_ok else "warn", "detail": str(db)},
        {"name": "Codex hooks", "status": "ok" if hooks_ok else "warn", "detail": str(home / "hooks.json")},
        {
            "name": "LaunchAgent",
            "status": "ok" if service["plist_exists"] and service["loaded"] else "warn",
            "detail": str(service["plist_path"]),
        },
        {"name": "Dashboard", "status": "ok" if service["ping"]["ok"] else "warn", "detail": service["url"]},
    ]
    status = "warn" if any(check["status"] == "warn" for check in checks) else "ok"
    return {
        "status": status,
        "checks": checks,
        "service": service,
        "paths": {
            "app_home": str(app_dir),
            "database": str(db),
            "codex_home": str(home),
            "hooks": str(home / "hooks.json"),
            "plist": str(service["plist_path"]),
            "stdout_log": str(app_dir / "logs" / "daemon.stdout.log"),
            "stderr_log": str(app_dir / "logs" / "daemon.stderr.log"),
        },
        "commands": {
            "doctor_fix": f"uv run aikeeper doctor --fix --port {port}",
            "install_all": f"uv run aikeeper install all --port {port}",
            "service_status": f"uv run aikeeper service status --port {port} --json",
            "service_restart": "uv run aikeeper service restart",
            "diagnostics_bundle": f"uv run aikeeper diagnostics bundle --port {port}",
        },
        "actions": list(SYSTEM_ACTIONS),
    }


def _action_command(action: str, port: int, root: Path) -> list[str]:
    base = ["uv", "--directory", str(root), "run", "aikeeper"]
    if action == "repair":
        return [*base, "doctor", "--fix", "--port", str(port)]
    if action == "reinstall":
        return [*base, "install", "all", "--port", str(port)]
    if action == "restart":
        return [*base, "service", "restart"]
    if action == "diagnostics":
        return [*base, "diagnostics", "bundle", "--port", str(port)]
    raise KeyError(action)


def _launch_system_action(action: str, port: int) -> dict[str, str]:
    root = project_root() or Path.cwd()
    command = _action_command(action, port, root)
    logs_dir = app_home() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "system-actions.log"
    shell_command = " ".join(shlex.quote(part) for part in command)
    subprocess.Popen(
        ["/bin/sh", "-lc", f"sleep 1; {shell_command} >> {shlex.quote(str(log_path))} 2>&1"],
        cwd=root,
        start_new_session=True,
    )
    return {"status": "queued", "action": action, "log_path": str(log_path)}


def _run_polling_sync(db: Path, home: Path, stop: threading.Event, interval_seconds: int = 5) -> None:
    sync_codex_once(db_path=db, codex_home=home)
    while not stop.wait(interval_seconds):
        sync_codex_once(db_path=db, codex_home=home)


def create_app(
    *,
    db_path: Path | str | None = None,
    codex_home: Path | str | None = None,
    budget_path: Path | str | None = None,
    auto_sync: bool = False,
) -> FastAPI:
    db = Path(db_path).expanduser() if db_path else default_db_path()
    home = Path(codex_home).expanduser() if codex_home else default_codex_home()
    budgets = Path(budget_path).expanduser() if budget_path else None
    with connect(db) as con:
        init_db(con)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = threading.Event()
        thread: threading.Thread | None = None
        if auto_sync:
            thread = threading.Thread(target=_run_polling_sync, args=(db, home, stop), daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread:
                thread.join(timeout=1)

    app = FastAPI(title="AI Keeper", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/api/ping")
    def api_ping() -> dict:
        return {"ok": True, "service": "aikeeper", "version": get_app_version()}

    @app.get("/api/overview")
    def api_overview() -> dict:
        data = overview(db, budget_path=budgets)
        data["version"] = get_app_version()
        return data

    @app.get("/api/budgets")
    def api_budgets() -> dict:
        config = load_budget_config_from_db(db)
        return {
            "configured": config.configured,
            "source_path": config.source_path,
            "warn_at": config.warn_at,
            "limits": config.limits,
            "task_limits": config.task_limits,
        }

    @app.get("/api/simulate")
    def api_simulate(target_model: str) -> dict:
        return simulate_model_cost(db, target_model=target_model)

    @app.get("/api/health/ingest")
    def api_ingest_health() -> dict:
        return ingest_health(db)

    @app.get("/api/system")
    def api_system(request: Request) -> dict:
        host, port = _request_host_port(request)
        data = _system_status(db=db, home=home, host=host, port=port)
        data["version"] = get_app_version()
        return data

    @app.get("/api/diagnostics")
    def api_diagnostics() -> dict:
        return diagnostics_overview()

    @app.get("/api/audit/privacy")
    def api_privacy_audit() -> dict:
        return audit_privacy(db)

    @app.post("/api/sync/codex")
    def api_sync_codex() -> dict:
        result = sync_codex_once(db_path=db, codex_home=home)
        return {"sessions_imported": result.sessions_imported, "token_events_imported": result.token_events_imported}

    @app.post("/budgets")
    async def save_budgets(request: Request) -> RedirectResponse:
        form = await _read_form(request)
        save_budget_settings(
            db,
            scope=form.get("scope", "defaults"),
            scope_key=form.get("task_key", ""),
            warn_at=form.get("warn_at"),
            limits={key: form.get(key, "") for key in LIMIT_DEFINITIONS},
        )
        return RedirectResponse("/budgets", status_code=303)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "overview.html",
            {"overview": overview(db, budget_path=budgets), "version": get_app_version(), "active_page": "command"},
        )

    @app.get("/usage", response_class=HTMLResponse)
    def usage(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "usage.html",
            {"overview": overview(db, budget_path=budgets), "version": get_app_version(), "active_page": "usage"},
        )

    @app.get("/models", response_class=HTMLResponse)
    def models(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "models.html",
            {"overview": overview(db, budget_path=budgets), "version": get_app_version(), "active_page": "models"},
        )

    @app.get("/budgets", response_class=HTMLResponse)
    def budget_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "budgets.html",
            {"overview": overview(db, budget_path=budgets), "version": get_app_version(), "active_page": "budgets"},
        )

    @app.get("/health", response_class=HTMLResponse)
    def health(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "health.html",
            {"overview": overview(db, budget_path=budgets), "version": get_app_version(), "active_page": "health"},
        )

    @app.get("/system", response_class=HTMLResponse)
    def system(request: Request) -> HTMLResponse:
        host, port = _request_host_port(request)
        return templates.TemplateResponse(
            request,
            "system.html",
            {
                "system": _system_status(db=db, home=home, host=host, port=port),
                "version": get_app_version(),
                "active_page": "system",
            },
        )

    @app.get("/diagnostics", response_class=HTMLResponse)
    def diagnostics_page(request: Request) -> HTMLResponse:
        created = request.query_params.get("created", "")
        return templates.TemplateResponse(
            request,
            "diagnostics.html",
            {
                "diagnostics": diagnostics_overview(),
                "created": created,
                "version": get_app_version(),
                "active_page": "diagnostics",
            },
        )

    @app.post("/diagnostics/bundles")
    def create_diagnostics_page_bundle(request: Request) -> RedirectResponse:
        host, port = _request_host_port(request)
        archive = create_diagnostics_bundle(db_path=db, host=host, port=port)
        append_system_action_log(f"Created AI Keeper diagnostics bundle: {archive}")
        return RedirectResponse(f"/diagnostics?created={archive.name}", status_code=303)

    @app.get("/diagnostics/bundles/{filename}")
    def download_diagnostics_bundle(filename: str) -> FileResponse:
        try:
            bundle = resolve_diagnostics_bundle(filename)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="diagnostics bundle not found") from exc
        return FileResponse(
            bundle,
            media_type="application/zip",
            filename=bundle.name,
        )

    @app.post("/system/actions/{action}")
    async def system_action(request: Request, action: str) -> RedirectResponse:
        if action not in {item["key"] for item in SYSTEM_ACTIONS}:
            raise HTTPException(status_code=404, detail="unknown action")
        form = await _read_form(request)
        if form.get("confirm") != action:
            raise HTTPException(status_code=400, detail="confirmation mismatch")
        _host, port = _request_host_port(request)
        try:
            _launch_system_action(action, port)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown action") from exc
        return RedirectResponse(f"/system?action={action}", status_code=303)

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project(request: Request, project_id: int) -> HTMLResponse:
        try:
            data = project_detail(db, project_id, budget_path=budgets)
        except KeyError as exc:
            raise HTTPException(status_code=404) from exc
        data["version"] = get_app_version()
        data["active_page"] = "usage"
        return templates.TemplateResponse(request, "project.html", data)

    @app.get("/sessions/{session_id}", response_class=HTMLResponse)
    def session(request: Request, session_id: int) -> HTMLResponse:
        try:
            data = session_detail(db, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404) from exc
        data["version"] = get_app_version()
        data["active_page"] = "usage"
        return templates.TemplateResponse(request, "session.html", data)

    return app


async def _read_form(request: Request) -> dict[str, str]:
    body = (await request.body()).decode("utf-8")
    parsed = parse_qs(body, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in parsed.items()}


def _request_host_port(request: Request) -> tuple[str, int]:
    host = request.url.hostname or DEFAULT_HOST
    if host == "testserver":
        host = DEFAULT_HOST
    return host, request.url.port or 8766

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aikeeper.audit import audit_privacy
from aikeeper.codex import sync_codex_once
from aikeeper.db import connect, init_db
from aikeeper.health import ingest_health
from aikeeper.service import overview, project_detail, session_detail, simulate_model_cost
from aikeeper.settings import budget_config_path as default_budget_config_path
from aikeeper.settings import codex_home as default_codex_home
from aikeeper.settings import default_db_path
from aikeeper.version import get_app_version


PACKAGE_DIR = Path(__file__).parent
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


templates.env.filters["tokens"] = format_tokens
templates.env.filters["compact_tokens"] = compact_tokens
templates.env.filters["usd"] = format_usd
templates.env.filters["compact_usd"] = compact_usd
templates.env.filters["per_minute"] = compact_per_minute
templates.env.filters["usd_per_minute"] = usd_per_minute
templates.env.filters["percent"] = percent


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
    budgets = Path(budget_path).expanduser() if budget_path else default_budget_config_path()
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

    @app.get("/api/overview")
    def api_overview() -> dict:
        data = overview(db, budget_path=budgets)
        data["version"] = get_app_version()
        return data

    @app.get("/api/simulate")
    def api_simulate(target_model: str) -> dict:
        return simulate_model_cost(db, target_model=target_model)

    @app.get("/api/health/ingest")
    def api_ingest_health() -> dict:
        return ingest_health(db)

    @app.get("/api/audit/privacy")
    def api_privacy_audit() -> dict:
        return audit_privacy(db)

    @app.post("/api/sync/codex")
    def api_sync_codex() -> dict:
        result = sync_codex_once(db_path=db, codex_home=home)
        return {"sessions_imported": result.sessions_imported, "token_events_imported": result.token_events_imported}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "overview.html",
            {"overview": overview(db, budget_path=budgets), "version": get_app_version()},
        )

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    def project(request: Request, project_id: int) -> HTMLResponse:
        try:
            data = project_detail(db, project_id, budget_path=budgets)
        except KeyError as exc:
            raise HTTPException(status_code=404) from exc
        data["version"] = get_app_version()
        return templates.TemplateResponse(request, "project.html", data)

    @app.get("/sessions/{session_id}", response_class=HTMLResponse)
    def session(request: Request, session_id: int) -> HTMLResponse:
        try:
            data = session_detail(db, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404) from exc
        data["version"] = get_app_version()
        return templates.TemplateResponse(request, "session.html", data)

    return app

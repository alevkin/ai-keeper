from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from aikeeper.audit import audit_privacy
from aikeeper.health import ingest_health
from aikeeper.launchd import default_launch_agent_path, launch_agent_status
from aikeeper.settings import DEFAULT_HOST, DEFAULT_PORT, app_home
from aikeeper.timeutils import now_ms
from aikeeper.version import get_app_version


TAIL_BYTES = 64_000


def _read_tail(path: Path, limit: int = TAIL_BYTES) -> str:
    if not path.exists():
        return ""
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(size - limit, 0))
        return handle.read().decode("utf-8", errors="replace")


def _write_json(package: zipfile.ZipFile, name: str, data: dict[str, Any]) -> None:
    package.writestr(name, json.dumps(data, indent=2, sort_keys=True) + "\n")


def _summary_markdown(*, db_path: Path, service: dict, privacy: dict, health: dict, archive_name: str) -> str:
    return "\n".join(
        [
            "# AI Keeper Diagnostics",
            "",
            "Metadata-only diagnostics bundle.",
            "No prompts, assistant messages, raw transcripts, or database files are included.",
            "",
            f"- Archive: `{archive_name}`",
            f"- Database path: `{db_path}`",
            f"- Dashboard: `{service.get('url')}`",
            f"- Service loaded: `{service.get('loaded')}`",
            f"- Service ping: `{service.get('ping', {}).get('ok')}`",
            f"- Privacy status: `{privacy.get('status')}`",
            f"- Ingest status: `{health.get('status')}`",
            f"- Ingest issues: `{', '.join(health.get('issues') or []) or 'none'}`",
            "",
        ]
    )


def create_diagnostics_bundle(
    *,
    db_path: Path | str,
    output_dir: Path | str | None = None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> Path:
    db = Path(db_path).expanduser()
    out = Path(output_dir).expanduser() if output_dir else app_home() / "diagnostics"
    out.mkdir(parents=True, exist_ok=True)
    generated_at_ms = now_ms()
    archive = out / f"aikeeper-diagnostics-{generated_at_ms}.zip"

    service = launch_agent_status(host=host, port=port, plist_path=default_launch_agent_path())
    privacy = audit_privacy(db)
    health = ingest_health(db, now_ms=generated_at_ms)
    logs_dir = app_home() / "logs"
    manifest = {
        "name": "AI Keeper diagnostics",
        "metadata_only": True,
        "generated_at_ms": generated_at_ms,
        "version": get_app_version(),
        "included": [
            "doctor.json",
            "privacy.json",
            "ingest_health.json",
            "service_status.json",
            "logs/daemon.stdout.tail.txt",
            "logs/daemon.stderr.tail.txt",
        ],
        "excluded": ["prompts", "assistant_messages", "raw_transcripts", "sqlite_database"],
    }
    doctor = {
        "status": "fail"
        if privacy.get("status") == "fail"
        else "warn"
        if health.get("status") == "warn" or not service.get("ping", {}).get("ok")
        else "ok",
        "database_path": str(db),
        "service": {
            "loaded": service.get("loaded"),
            "url": service.get("url"),
            "ping": service.get("ping"),
            "plist_path": service.get("plist_path"),
            "plist_exists": service.get("plist_exists"),
        },
        "privacy_status": privacy.get("status"),
        "ingest_status": health.get("status"),
    }

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        _write_json(package, "manifest.json", manifest)
        _write_json(package, "doctor.json", doctor)
        _write_json(package, "privacy.json", privacy)
        _write_json(package, "ingest_health.json", health)
        _write_json(package, "service_status.json", service)
        package.writestr(
            "summary.md",
            _summary_markdown(db_path=db, service=service, privacy=privacy, health=health, archive_name=archive.name),
        )
        package.writestr("logs/daemon.stdout.tail.txt", _read_tail(logs_dir / "daemon.stdout.log"))
        package.writestr("logs/daemon.stderr.tail.txt", _read_tail(logs_dir / "daemon.stderr.log"))
    return archive

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from aikeeper.service import overview, task_budget_status


def export_usage(
    db_path: Path | str,
    fmt: str,
    *,
    budget_path: Path | str | None = None,
    now_ms: int | None = None,
) -> str:
    data = overview(db_path, now_ms=now_ms, budget_path=budget_path)
    task_status = task_budget_status(db_path, budget_path=budget_path, now_ms=now_ms)
    payload = {
        "privacy": "metadata-only",
        "overview": data,
        "task_budget_status": task_status,
    }

    if fmt == "json":
        return json.dumps(payload, indent=2, sort_keys=True)
    if fmt == "csv":
        handle = io.StringIO()
        writer = csv.writer(handle)
        writer.writerow(["project", "task", "total_tokens", "budget_status"])
        for row in task_status:
            status = row["budget_warnings"][0]["severity"] if row["budget_warnings"] else "ok"
            writer.writerow([row["project_name"], row["task_key"], row["total_tokens"], status])
        return handle.getvalue()
    if fmt == "markdown":
        lines = [
            "# AI Keeper Usage Export",
            "",
            "Privacy: metadata-only. No prompts, assistant messages, or raw transcripts are included.",
            "",
            f"Total tokens: {data['total_tokens']:,}",
            f"Estimated total spend: ${data['estimated_cost']['total_usd']:.2f}",
            "",
            "## Task Budgets",
            "",
            "| Project | Task | Total tokens | Budget |",
            "| --- | --- | ---: | --- |",
        ]
        for row in task_status:
            status = "budget over" if row["budget_warnings"] else "ok"
            lines.append(f"| {row['project_name']} | {row['task_key']} | {row['total_tokens']:,} | {status} |")
        return "\n".join(lines) + "\n"
    raise ValueError("format must be json, csv, or markdown")

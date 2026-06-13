from __future__ import annotations

import json
from pathlib import Path

import httpx

from aikeeper.db import connect, init_db
from aikeeper.timeutils import now_ms


OPENAI_COSTS_URL = "https://api.openai.com/v1/organization/costs"


def import_costs_payload(db_path: Path | str, payload: dict, *, source: str = "openai-admin-costs") -> int:
    imported = 0
    with connect(db_path) as con:
        init_db(con)
        for bucket in payload.get("data", []):
            start = int(bucket.get("start_time") or 0)
            end = int(bucket.get("end_time") or 0)
            for result in bucket.get("results", []):
                amount = result.get("amount") or {}
                value = amount.get("value")
                currency = amount.get("currency") or "usd"
                if value is None:
                    continue
                cursor = con.execute(
                    """
                    insert or ignore into external_costs(
                        provider, source, bucket_start_s, bucket_end_s, amount_value, currency,
                        line_item, project_ref, api_key_ref, quantity, raw_json, imported_at_ms
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "openai",
                        source,
                        start,
                        end,
                        float(value),
                        str(currency),
                        result.get("line_item"),
                        result.get("project_id") or "",
                        result.get("api_key_id") or "",
                        result.get("quantity"),
                        json.dumps(result, sort_keys=True),
                        now_ms(),
                    ),
                )
                if cursor.rowcount > 0:
                    imported += 1
        con.commit()
    return imported


def fetch_and_import_costs(
    db_path: Path | str,
    *,
    admin_key: str,
    start_time: int,
    end_time: int | None = None,
    limit: int = 180,
    group_by: str | None = None,
) -> int:
    params: dict[str, str | int] = {"start_time": start_time, "limit": limit}
    if end_time:
        params["end_time"] = end_time
    if group_by:
        params["group_by"] = group_by
    response = httpx.get(
        OPENAI_COSTS_URL,
        params=params,
        headers={"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return import_costs_payload(db_path, response.json())

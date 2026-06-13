from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA = """
create table if not exists projects (
    id integer primary key autoincrement,
    root_path text not null unique,
    name text not null,
    git_origin text,
    first_seen_ms integer not null,
    last_seen_ms integer not null
);

create table if not exists tasks (
    id integer primary key autoincrement,
    project_id integer not null references projects(id) on delete cascade,
    task_key text not null,
    source text not null,
    git_branch text,
    issue_id text,
    display_name text not null,
    first_seen_ms integer not null,
    last_seen_ms integer not null,
    unique(project_id, task_key)
);

create table if not exists sessions (
    id integer primary key autoincrement,
    provider text not null,
    session_id text not null,
    transcript_path text,
    cwd text not null,
    model text,
    model_provider text,
    source text,
    project_id integer not null references projects(id) on delete cascade,
    task_id integer not null references tasks(id) on delete cascade,
    git_sha text,
    git_branch text,
    git_origin_url text,
    created_at_ms integer not null,
    updated_at_ms integer not null,
    total_tokens integer not null default 0,
    last_seen_ms integer not null,
    unique(provider, session_id)
);

create table if not exists token_events (
    id integer primary key autoincrement,
    session_pk integer not null references sessions(id) on delete cascade,
    sequence integer not null,
    timestamp_ms integer not null,
    input_tokens integer not null default 0,
    cached_input_tokens integer not null default 0,
    output_tokens integer not null default 0,
    reasoning_output_tokens integer not null default 0,
    total_tokens integer not null default 0,
    running_total_tokens integer not null default 0,
    source_path text,
    source_offset integer not null default 0,
    unique(session_pk, sequence)
);

create table if not exists ingest_state (
    source_key text primary key,
    last_offset integer not null default 0,
    updated_at_ms integer not null,
    meta_json text not null default '{}'
);

create table if not exists external_costs (
    id integer primary key autoincrement,
    provider text not null,
    source text not null,
    bucket_start_s integer not null,
    bucket_end_s integer not null,
    amount_value real not null,
    currency text not null,
    line_item text,
    project_ref text,
    api_key_ref text,
    quantity real,
    raw_json text not null default '{}',
    imported_at_ms integer not null,
    unique(provider, source, bucket_start_s, bucket_end_s, line_item, project_ref, api_key_ref)
);

create index if not exists idx_sessions_cwd on sessions(cwd);
create index if not exists idx_sessions_project on sessions(project_id);
create index if not exists idx_sessions_task on sessions(task_id);
create index if not exists idx_token_events_session on token_events(session_pk, sequence);
create index if not exists idx_token_events_timestamp on token_events(timestamp_ms);
create index if not exists idx_external_costs_bucket on external_costs(provider, bucket_start_s);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    con.execute("pragma journal_mode = wal")
    return con


def init_db(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()
